# Hybridní retrieval (dense + sparse) — design

_Verze: v1, přijato 2026-08-04._

## Cíl

Navázat na existující chunking (`law_agent.ingestion`) indexací do Qdrantu a
hybridním (dense + sparse) hledáním, jak předpokládá [[project-spec]]. Cílem
tohoto kroku je odladit RAG na jednom konkrétním zákoníku (MVP roadmapa, bod 1).

## Architektura

Jedna Qdrant kolekce `chunks`, sdílená pro všechny tři namespaces (`laws`,
`org_files`, `user_files` — viz project-spec). Namespace i budoucí role-based
filtrace (org_files) jsou payload pole s indexem, ne oddělené kolekce.

Každý bod nese dva pojmenované vektory:

- **`dense`** — 1024dim embedding z `chunk.text`, počítaný přes stávající
  `OpenRouterEmbeddings` (`law_agent/core/embeddings.py`), cosine distance.
- **`sparse`** — BM25 sparse vektor (token → váha) z téhož `chunk.text`,
  počítaný **lokálně** přes FastEmbed (`Qdrant/bm25`), bez volání API a bez ML
  inference. Qdrant sparse vector s `modifier=IDF`.

Dotaz se řeší jedním voláním Qdrant Query API: `prefetch` s dense i sparse
větví (obě filtrované na `namespace`, případně další payload filtry), fúze
`Fusion.RRF` (Reciprocal Rank Fusion) — Qdrant fúzi dělá nativně, žádný ruční
merge skóre v aplikační vrstvě.

### Proč BM25 přes FastEmbed teď, ne bge-m3 nativní sparse

BGE-M3 umí z jednoho běhu vrátit dense i sparse (`lexical_weights`) výstup,
ale **jen přes knihovnu FlagEmbedding přímo** (self-hosted inference), ne přes
generický embeddings endpoint. Ověřeno:

- OpenRouter `/embeddings` je OpenAI-kompatibilní, vrací jen `data[].embedding`
  (dense floats) — žádný sparse výstup.
- TEI (zakomentovaná služba v `docker-compose.yml`) je stavěná na dense
  pooling, ne na BGE-M3 multi-functionality výstup.

Embeddings teď jedou přes OpenRouter (self-hosting je podle project-spec
pozdější fáze), takže dense a sparse musí vznikat odděleně. FastEmbed BM25 je
čistě statistický (IDF), běží lokálně na CPU bez závislosti na modelu.

**Cesta k upgrade later:** schéma je navržené tak, že přechod na bge-m3
nativní sparse znamená jen výměnu funkce, která plní `sparse` vektor
(FastEmbed → FlagEmbedding), beze změny kolekce nebo query kódu — formát
(token → váha) je stejný.

## Schéma kolekce

```
collection: chunks
vectors:
  dense:  size=1024, distance=Cosine
sparse_vectors:
  sparse: modifier=IDF
payload:
  namespace: keyword index   # "laws" | "org_files" | "user_files"
  + zbytek Chunk.to_payload() (law_id, section, citation, is_effective, ...)
point_id: chunk.point_id     # UUIDv5, deterministický → upsert místo duplikace
```

`user_files` (in-session, netrvalé) jdou do stejné kolekce; mazání/TTL na
konci session se řeší až v té fázi (mimo rozsah tohoto designu) — teď jen
počítáme s polem `namespace` (a případně `session_id`) v payloadu.

## Indexační flow

Nový modul `law_agent/indexing/`:

1. Načíst chunky (výstup `LawChunker`).
2. Pro každý chunk porovnat `content_hash` s tím, co už je v Qdrantu →
   přeskočit nezměněné.
3. Pro zbylé (po dávkách): `embed_documents([c.text for c in batch])`
   (OpenRouter) + lokální BM25 sparse vektor (FastEmbed, bez volání sítě).
4. Upsert do Qdrantu pod `point_id`, oba vektory + payload.

## Query flow

Nový modul `law_agent/retrieval/`:

1. Dotaz → dense embedding (OpenRouter) + sparse vektor (FastEmbed) ze
   stejného textu dotazu.
2. Jedno `client.query_points(prefetch=[dense, sparse], fusion=RRF, limit=k)`,
   s payload filtrem na `namespace` (a případně `is_effective`, `law_id`).
3. Výsledek: seřazené chunky s `citation`, `text`, `law_citation` — přímo
   použitelné pro citaci zdroje (project-spec: MVP citace = odkaz na dokument
   + paragraf/stránka).

## Nové závislosti

`qdrant-client`, `fastembed`.

## Testování

Unit testy nad in-memory Qdrant instancí (`qdrant-client`'s `:memory:` mode):

- upsert + skip nezměněných chunků podle `content_hash`,
- doslovný dotaz (`§ 41`) najde očekávaný chunk (sparse větev),
- sémantický dotaz (`převedení na jinou práci`) najde očekávaný chunk (dense
  větev),
- namespace filtr skutečně omezuje výsledky.

`OpenRouterEmbeddings.embed_documents` (jediné síťové volání v této vrstvě) se
v unit testech mockuje/stubuje, aby testy neplatily za API a nezávisely na
síti.

### Manuální query skript

Nový `scripts/query_laws.py`, ve stylu `scripts/chunk_laws.py`. Účel: ruční
kontrola kvality retrievalu nad reálně naindexovanými zákony z `data/laws/`
(ne in-memory testovací instance výše — reálný běžící Qdrant z
`docker-compose.yml`).

```bash
uv run scripts/query_laws.py "kdy musí zaměstnavatel převést zaměstnance na jinou práci"
uv run scripts/query_laws.py "§ 52 písm. c)" --limit 10
```

Flow:

1. Před dotazem si skript vždy sám zavolá indexaci `data/laws/*.json` do
   kolekce `chunks` (idempotentní upsert, viz níže — nikdy nehrozí duplicity
   ani zastaralá data, jen zbytečné volání API při nezměněných chunkách, což
   řeší `content_hash` skip).
2. Vzít dotaz z CLI argumentu, spustit hybridní `query_points` (dense + sparse
   + RRF fúze) přes `law_agent/retrieval/`.
3. Uložit výsledek (dotaz, vrácené chunky se skóre, `citation`, `text`) do
   JSON souboru v `data/` (např. `data/query_results/<timestamp>.json`), aby
   šlo výsledky procházet a porovnávat mezi změnami chunkeru/indexace.

### Idempotence indexace (žádné duplicity)

`point_id = uuid5(chunk_id)` je deterministický, ne náhodný — Qdrant `upsert`
zapisuje "vlož nebo přepiš podle `point_id`". Opakované spuštění indexace
(ať už ze `scripts/query_laws.py`, nebo samostatně) tedy vždy přepisuje stejné
body, nikdy nevytváří duplicity. `content_hash` check navíc přeskočí
přeembedování nezměněných chunků, aby se neplatilo za API zbytečně — ale i bez
něj by opakovaný běh byl bezpečný, jen dražší.

## Mimo rozsah

- Role-based filtrace nad `org_files` (auth systém neexistuje — project-spec,
  otevřené rozhodnutí).
- TTL/mazání `user_files` na konci session.
- Self-hosting bge-m3 a přechod na jeho nativní sparse výstup.
- LangChain vs LangGraph orchestrace nad retrievalem.
