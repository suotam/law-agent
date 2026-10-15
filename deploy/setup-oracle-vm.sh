#!/usr/bin/env bash
# One-shot setup of the whole Law Agent stack (API + frontend) on a fresh
# Oracle Cloud "Always Free" Ampere VM running Ubuntu 24.04 (aarch64).
#
#   scp deploy/setup-oracle-vm.sh ubuntu@<VM-IP>:setup.sh   # from a local checkout
#   ssh ubuntu@<VM-IP>
#   bash setup.sh
#
# The script is idempotent: re-running updates the repos and restarts the
# stack. Secrets are asked for interactively on the first run and kept in
# ~/law-agent/.env.prod; they are never echoed or committed.
#
# Ports: 80 (frontend) and 8000 (API) are opened in the VM's own iptables.
# The same two ports must also be opened in the OCI console (VCN security
# list) — see deploy/DEPLOY_ORACLE.md, the script cannot do that part.

set -euo pipefail

REPO_URL="https://github.com/suotam/law-agent.git"
BASE="$HOME"

# The repository is private, so cloning needs a token: a fine-grained PAT
# with read-only "Contents" permission on the repo (github.com ->
# Settings -> Developer settings -> Fine-grained tokens). It is written to
# ~/.git-credentials (0600) on this VM only.
if [ ! -f "$HOME/.git-credentials" ]; then
  read -rp "GitHub token with read access to the law-agent repo: " GITHUB_TOKEN
  git config --global credential.helper store
  printf 'https://x-access-token:%s@github.com
' "$GITHUB_TOKEN" > "$HOME/.git-credentials"
  chmod 600 "$HOME/.git-credentials"
fi

echo "==> Public IP of this VM"
PUBLIC_IP=$(curl -fsS ifconfig.me)
echo "    $PUBLIC_IP"

echo "==> Installing Docker (if missing)"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

echo "==> Opening ports 80 and 8000 in the VM firewall"
# Oracle's Ubuntu images ship an iptables INPUT chain that drops everything
# but SSH; ufw is not active. Insert before the drop rule and persist.
for port in 80 8000; do
  sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 5 -p tcp --dport "$port" -j ACCEPT
done
sudo netfilter-persistent save 2>/dev/null || sudo sh -c 'iptables-save > /etc/iptables/rules.v4' || true

echo "==> Cloning / updating the repository"
dir="$BASE/$(basename "$REPO_URL" .git)"
if [ -d "$dir/.git" ]; then git -C "$dir" pull --ff-only; else git clone "$REPO_URL" "$dir"; fi

 REPO="$BASE/law-agent"

echo "==> Backend secrets (.env.prod)"
if [ ! -f "$REPO/.env.prod" ]; then
  read -rp "OPENROUTER_API_KEY: " OPENROUTER_API_KEY
  read -rp "CESKEZAKONY_API_TOKEN (empty to skip law ingestion): " CESKEZAKONY_API_TOKEN
  JWT_SECRET=$(openssl rand -hex 64)
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  cat > "$REPO/.env.prod" <<ENV
ENVIRONMENT=production
OPENROUTER_API_KEY=$OPENROUTER_API_KEY
OPENROUTER_MODEL=qwen/qwen3-235b-a22b-2507
OPENROUTER_EMBEDDING_MODEL=baai/bge-m3
OPENROUTER_PROVIDER={"zdr": true, "data_collection": "deny"}
CESKEZAKONY_API_TOKEN=$CESKEZAKONY_API_TOKEN
QDRANT_COLLECTION=chunks
BLOB_ROOT=data/blobs
JWT_SECRET=$JWT_SECRET
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
CORS_ORIGINS=["http://$PUBLIC_IP"]
ENV
  chmod 600 "$REPO/.env.prod"
  echo "    written to $REPO/.env.prod"
else
  echo "    $REPO/.env.prod already exists, keeping it"
fi

echo "==> Frontend build config (.env)"
# Compose interpolates ${VITE_BACKEND_API_URL} for the frontend image build
# from .env in the project directory (api secrets stay in .env.prod).
printf 'VITE_BACKEND_API_URL=http://%s:8000\n' "$PUBLIC_IP" > "$REPO/.env"

echo "==> Building and starting the stack (first run downloads ~4 GB)"
sudo docker compose -f "$REPO/docker-compose.prod.yml" --project-directory "$REPO" up -d --build

echo "==> Waiting for the API to answer"
for _ in $(seq 1 60); do
  curl -fsS -o /dev/null http://localhost:8000/openapi.json 2>/dev/null && break
  curl -fsS -o /dev/null -w '' http://localhost:8000/ 2>/dev/null && break
  sleep 2
done

echo "==> Applying database migrations"
sudo docker compose -f "$REPO/docker-compose.prod.yml" --project-directory "$REPO" exec api alembic upgrade head

cat <<DONE

============================================================
Stack is up.

  Frontend:  http://$PUBLIC_IP
  API:       http://$PUBLIC_IP:8000

Remaining one-time steps (run on this VM):

  1. Create the first admin account:
     sudo docker compose -f ~/law-agent/docker-compose.prod.yml exec api \
         uv run scripts/create_user.py you@example.com --role admin

  2. Ingest the laws you need (repeat per law):
     sudo docker compose -f ~/law-agent/docker-compose.prod.yml exec api \
         uv run scripts/ingest_law_url.py https://ceskezakony.cz/api/v1/laws/106/1999/fragments

If the site is unreachable from outside, open ports 80 and 8000 in the
OCI console: VCN -> Security List -> Ingress Rules (see DEPLOY_ORACLE.md).
============================================================
DONE
