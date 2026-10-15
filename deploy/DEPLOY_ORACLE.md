# Deploying to an Oracle Cloud "Always Free" VM

The whole stack — API, Postgres, Qdrant, docling and the React frontend —
fits on one Always Free Ampere VM. Hosting costs nothing; the only running
cost stays the OpenRouter usage. The site is served over plain HTTP on the
VM's IP (the frontend lives on the same origin as a result, so no
mixed-content issues); add a domain + Caddy later if HTTPS is needed.

## 1. Create the account and the VM (in the browser)

1. Sign up at <https://signup.oraclecloud.com> (a card is required for
   identity verification; the Always Free tier itself never charges — the
   account cannot be billed unless it is explicitly upgraded).
2. Pick a **home region** close to you (e.g. Germany Central / Frankfurt).
   This cannot be changed later, and Always Free ARM capacity varies by
   region — Frankfurt and Amsterdam usually have it.
3. Console → **Compute → Instances → Create instance**:
   - Image: **Ubuntu 24.04** (aarch64).
   - Shape: **Ampere → VM.Standard.A1.Flex**, 4 OCPU / 24 GB RAM (the
     Always Free maximum; using all of it in one VM is simplest).
   - Networking: accept the default VCN; make sure **Assign a public IPv4
     address** is checked.
   - Add your SSH public key (`ssh-keygen -t ed25519` if you have none).
   - Boot volume: up to 200 GB is free; 100 GB is plenty.
   - If creation fails with "Out of capacity", retry later or try another
     availability domain — free ARM capacity fluctuates.
4. Open the ports in the VCN firewall: **Networking → Virtual cloud
   networks → (your VCN) → Security Lists → Default Security List → Add
   Ingress Rules**, twice:
   - Source CIDR `0.0.0.0/0`, protocol TCP, destination port `80`
   - Source CIDR `0.0.0.0/0`, protocol TCP, destination port `8000`

## 2. Run the setup script (over SSH)

The repository is private, so first create a **fine-grained personal access
token** the VM will clone with: github.com -> Settings -> Developer settings
-> Personal access tokens -> Fine-grained tokens -> Generate new token,
repository access limited to `law-agent`, permission **Contents: Read-only**.
The script asks for it on first run.

```bash
# from your machine, in the law-agent checkout:
scp deploy/setup-oracle-vm.sh ubuntu@<VM-IP>:setup.sh

ssh ubuntu@<VM-IP>
bash setup.sh
```

The script installs Docker, opens the same two ports in the VM's own
iptables (Oracle images drop everything but SSH by default — the VCN rule
from step 1.4 alone is not enough), clones the `law-agent` repository
(backend and frontend live in it), asks for the GitHub token, the OpenRouter
and ceskezakony keys (generating `JWT_SECRET` and `POSTGRES_PASSWORD`
itself), builds and starts everything, and runs the database migrations.
First run takes ~10 minutes, dominated by the docling image download.

Then follow the two numbered commands it prints at the end: create the
first admin account and ingest the laws. Both run inside the `api`
container, matching the README's production instructions.

## 3. Day-2 operations

- **Update to the latest code**: re-run `bash setup.sh` — it pulls the repo
  and rebuilds. Apply migrations after schema changes (the script
  runs them every time; that is a no-op when nothing changed).
- **Logs**: `sudo docker logs -f law-agent-api`
- **Add a user for a tester**: same `create_user.py` command with
  `--role member`.
- **Costs guard**: set a spend limit on the OpenRouter key
  (<https://openrouter.ai/settings/keys>) so a tester cannot drain the
  credit.
- **What testers see**: everything indexed under both scopes, plus their
  own conversations. Give them `member`, never `admin`.

## Notes

- All images used (postgres, qdrant, docling-serve-cpu, uv's Python base,
  node, nginx) are published for linux/arm64, so nothing runs emulated.
- OpenAPI docs are disabled in production (`ENVIRONMENT=production`); the
  API answering 404 on `/docs` is expected.
- The frontend bakes the API URL at build time. If the VM's public IP ever
  changes (it survives reboots, but not instance re-creation), re-run
  `setup.sh` so the frontend is rebuilt against the new IP and
  `CORS_ORIGINS` is regenerated (delete `.env.prod` first, or edit the
  origin in place).
