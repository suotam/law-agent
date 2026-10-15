# Docling ingestion pro obecné soubory — design

_Verze: v1, přijato 2026-08-04._

> **Chunkovací část je nahrazena** specifikací
> `2026-08-08-file-chunking-size-first-design.md`: velikost rozhoduje, nadpisy
> zůstávají v těle chunku a `HybridChunker` se už nepoužívá. Zbytek dokumentu
> (parsování, docling-serve, OCR) platí dál.

## Cíl

Umožnit indexaci obecných dokumentů (PDF, DOCX, …) vedle zákonů: parsování
přes **docling-serve** v Dockeru s **Tesseract OCR pro češtinu**, chunkování
Doclingovým `HybridChunker`em na straně aplikace a zápis do namespace
`org_files` přes existující indexovací vrstvu.

Součástí je i rozdělení `ingestion/` na subpackages `laws/` a `files/` se
sdílenou vrstvou, aby byla hranice mezi zdroji vidět ve struktuře, ne jen
v konvenci pojmenování.

Tenhle design je přímým pokračováním
[source-agnostic chunk kontraktu](2026-08-04-source-agnostic-chunk-contract-design.md),
který si `Docling, FileChunk a upload flow` explicitně nechal mimo rozsah.
Naplňuje tedy jeho slib: přidání nového zdroje = přidání nového modulu.

**Namespace:** `org_files` (roadmapa [[project-spec]] bod 5) jde první, přestože
`user_files` je bod 3. Důvod je technický — org files nemají session, TTL ani
upload endpoint, takže se na nich dá odladit OCR a chunking bez dalších
pohyblivých částí. `user_files` pak sdílí tutéž pipeline a liší se jen
namespacem a životností.

## Rozhodnutí a jejich odůvodnění

### 1. Hybrid chunking běží u nás, ne v docling-serve

docling-serve umí chunkovat sám (`POST /v1/chunk/hybrid/file`). Přesto chunkuje
aplikace, přes `docling-core`:

- **Tokenizer.** Token budget `HybridChunker`u musí odpovídat embedding modelu.
  Projekt už má `ingestion/tokenizer.py` s protokolem `TokenCounter`
  (heuristika kalibrovaná na XLM-RoBERTa vocab BGE-M3 + volitelný exact HF
  counter). Klientsky se použije tentýž counter jako u zákonů. Server-side by
  tokenizer žil v konfiguraci kontejneru a musel by se ručně držet v souladu
  s `openrouter_embedding_model` — dvě místa pravdy.
- **Chunking je RAG rozhodnutí, ne parsovací.** Politika dělení textu patří
  vedle `ingestion/chunker.py`, ne do docker-compose configu. docling-serve
  zůstává čistý parser (bajty → `DoclingDocument`) a je tím nahraditelný.
- **Iterace.** Změna `max_tokens` nebo merge chování = změna kódu + `pytest`,
  ne rebuild kontejneru. Chunking jde unit-testovat.
- **Cache parsingu.** OCR skenu je nejdražší krok. Uložený `DoclingDocument`
  umožní přechunkovat bez opakovaného OCR; `/v1/chunk/hybrid/file` parse
  a chunking svazuje do jednoho volání.
- **Metadata.** Klientsky přijdou `DocChunk.meta` (headings, `doc_items`,
  `prov` se stránkami) jako typované objekty přímo do citace.

Cena: závislost `docling-core` (pydantic modely a transformace, žádné ML váhy).

### 2. Vlastní image nad `docling-serve-cpu`

`ghcr.io/docling-project/docling-serve-cpu` je multi-arch včetně `linux/arm64`,
takže na M1 běží nativně bez emulace. České `tessdata` v něm ale nejsou
a Tesseract v oficiálních images není spolehlivě zapojený (viz
[docling-serve#483](https://github.com/docling-project/docling-serve/issues/483)),
proto tenká vrstva navíc.

### 3. Auto OCR, ne force OCR

`do_ocr=true`, `force_ocr=false`. Digitálně vytvořená PDF použijí přesnou
textovou vrstvu, OCR se pustí jen na bitmapové oblasti. Force OCR by u čistých
PDF kvalitu snížil a všechno zpomalil.

### 4. `ingestion/` se rozdělí na `laws/` a `files/`

Dnešní `ingestion/` obsahuje výhradně law-specific moduly. Druhý zdroj by tam
přistál jako nerozlišená druhá vrstva, takže se před přidáním provede rozdělení
do subpackages a sdílená vrstva se udělá explicitní.

Fasáda `law_agent.ingestion` **přestane** re-exportovat law symboly; importy se
přesunou na `law_agent.ingestion.laws`. Kdyby fasáda zůstala, tvrdila by dál,
že `ingestion` = zákony — přesně to, co má rozdělení odstranit. Je to i
konzistentní s rozhodnutím ve
[specu chunk kontraktu](2026-08-04-source-agnostic-chunk-contract-design.md)
nezavádět zpětně kompatibilní aliasy, protože projekt nemá externí konzumenty.

### 5. `doc_id` z cesty souboru, sirotci se mažou

`doc_id` = relativní cesta v adresáři org files. Zrcadlí sémantiku `law_id`:
upravený dokument přepíše své chunky v místě. Protože nová verze může mít méně
chunků než stará, po upsertu se smažou zbylé body téhož `doc_id`.

## Architektura

```
soubor (PDF/DOCX/…)
   │
   ▼  multipart POST /v1/convert/file
┌──────────────────────────────┐
│ docling-serve  (kontejner)   │  jediná odpovědnost: bajty → DoclingDocument
│ + tesseract-ocr-ces          │  žádná znalost RAG, chunků ani Qdrantu
└──────────────────────────────┘
   │  json_content
   ▼
law_agent.ingestion.files
   ├─ client.py    DoclingClient — HTTP klient, mapování chyb
   ├─ chunker.py   HybridChunker + TokenCounter adaptér
   └─ models.py    FileChunk (splňuje ChunkLike strukturálně)
   │
   ▼  ChunkLike
indexing/ + retrieval/        beze změny, jen namespace "org_files"
                              (+ nová funkce prune_orphans)
```

`LawChunk` ani `LawChunker` se nedotýkáme. Jsou to dva nezávislí producenti
téhož kontraktu, bez sdílené dědičnosti a bez vzájemného importu.

### Reorganizace `ingestion/`

Provede se **před** přidáním Doclingu, jako samostatný krok, aby šlo ověřit,
že je čistě mechanická (viz Testování):

```
ingestion/
├── __init__.py       # jen sdílené: TokenCounter, make_point_id
├── tokenizer.py      # sdílené — používají oba chunkery
├── identity.py       # make_point_id (dnes v models.py)
├── laws/
│   ├── __init__.py   # LawDocument, LawChunker, LawChunk, validate, …
│   ├── chunker.py    ← ingestion/chunker.py
│   ├── document.py   ← ingestion/document.py
│   ├── models.py     ← ingestion/models.py
│   ├── taxonomy.py   ← ingestion/taxonomy.py
│   └── validation.py ← ingestion/validation.py
└── files/
    ├── __init__.py
    ├── client.py
    ├── chunker.py
    └── models.py
```

`make_point_id` se přesune do `ingestion/identity.py`, protože ho potřebují oba
modely. Kdyby zůstal v `laws/models.py`, musel by `files/models.py` importovat
z `laws/` a hranice by prosakovala hned prvním importem.

Moduly v subpackages nenesou prefix (`files/chunker.py`, ne
`files/file_chunker.py`) — subpackage jméno už nese, a
`law_agent.ingestion.files.chunker` je čitelnější než `...files.file_chunker`.

Mimo `ingestion/` se přesun dotkne pěti souborů:
`scripts/{chunk_laws,dump_chunks,query_laws}.py` a `tests/{factories,conftest}.py`,
plus tři test moduly (`test_chunker.py`, `test_document.py`, `test_real_laws.py`)
a odkazy na cesty v `docs/CHUNKING.md`.

## Docker

### `docker/docling/Dockerfile`

```dockerfile
FROM ghcr.io/docling-project/docling-serve-cpu:<pinned-tag>
USER root
RUN dnf install -y tesseract tesseract-langpack-ces tesseract-langpack-eng \
    leptonica-devel tesseract-devel && dnf clean all
RUN uv pip install --system "docling-serve[tesserocr]"
USER 1001
```

Base image je UBI/RHEL-based; přesný správce balíčků a jména langpacků se
ověří proti běžícímu image v prvním kroku implementace (na Debian variantě by
šlo o `apt-get install tesseract-ocr-ces`). Tag se **připíná**, nepoužívá se
`latest` — API docling-serve se mezi verzemi mění (viz Rizika).

### `docker-compose.yml`

Nová služba vedle Qdrantu:

```yaml
docling:
  build: ./docker/docling
  container_name: law-agent-docling
  restart: unless-stopped
  ports: ["5001:5001"]
  environment:
    DOCLING_SERVE_ENABLE_UI: "true"      # Gradio na :5001/ui pro vizuální kontrolu OCR
    DOCLING_SERVE_MAX_SYNC_WAIT: "600"   # OCR skenů na M1 CPU je pomalé
  volumes:
    - docling_models:/opt/app-root/src/.cache/docling/models
```

Poznámky k M1: běží `linux/arm64` nativně. GPU akcelerace v Dockeru na Macu
není možná (Docling na CPU využívá vlákna, ne Metal), pro cílové on-prem
nasazení na Linuxu je to irelevantní. Doporučená paměť pro Docker: ≥ 6 GB.

## Komponenty

### `ingestion/files/client.py`

```python
class DoclingClient:
    def parse(self, path: Path) -> DoclingDocument: ...
```

Multipart POST na `/v1/convert/file` s `to_formats=["json"]`, `do_ocr=true`,
`force_ocr=false`, `ocr_lang=["ces","eng"]`, `table_mode="accurate"`.
Z odpovědi bere `document.json_content` a validuje ho na `DoclingDocument`.

Chyby (`status: failure`, timeout, nedostupná služba) mapuje na vlastní
`DoclingError`, aby `httpx` typy neunikaly do volajícího.

Nové: závislost `httpx`, nastavení `Settings.docling_url`
(default `http://localhost:5001`).

### `ingestion/files/chunker.py`

`HybridChunker` z `docling-core` s adaptérem, který obalí existující
`TokenCounter` do Doclingova `BaseTokenizer` (`count_tokens`,
`get_max_tokens`). Embedovaný text vzniká přes `chunker.contextualize(chunk)`,
který před tělo vloží nadpisovou hierarchii — tedy stejná strategie jako
header u `LawChunk`, takže se dense i sparse index chová napříč namespacy
konzistentně.

### `ingestion/files/models.py` — `FileChunk`

Frozen pydantic model, strukturálně splňující `ChunkLike`, bez dědění
(stejně jako `LawChunk`).

| pole | zdroj |
|---|---|
| `chunk_id` | `f"{doc_id}#{chunk_index}"` |
| `point_id` | `uuid5` přes sdílený `make_point_id` |
| `content_hash` | `sha256(text)` |
| `text` | `chunker.contextualize(chunk)` |
| `header` / `body` | nadpisová hierarchie / `chunk.text` |
| `citation` | `"smlouvy/dodatek.pdf, s. 4 – Odstoupení od smlouvy"` |
| `doc_id`, `filename`, `pages`, `headings` | `chunk.meta` (`doc_items[].prov`) |
| `chunk_index`, `chunk_total`, `token_count`, `char_count` | dopočet |

`to_payload(namespace=...)` dodá všech pět povinných klíčů kontraktu
(`namespace`, `content_hash`, `chunk_id`, `citation`, `text`); `doc_id`,
`pages` a `headings` jdou navrch jako source-specific a k volajícímu doputují
přes `RetrievedChunk.payload`.

### Jediná změna v `indexing/`

```python
def prune_orphans(
    client, collection_name, *, scope: dict[str, str], keep: Sequence[str]
) -> int:
```

Smaže body odpovídající payload filtru `scope`
(`{"namespace": "org_files", "doc_id": ...}`), které nejsou mezi `keep`.
Funkce je generická a o org files nic neví — pro zákony by šla použít se
`scope={"law_id": ...}`.

Volá se **po** `index_chunks`, ne uvnitř, aby `index_chunks` zůstal čistě
aditivní a jeho stávající chování i testy se nezměnily.

Payload index pro `doc_id` se nezavádí; při dnešních objemech stačí filtr bez
indexu a zavedení indexu je kdykoli později aditivní změna.

### `scripts/ingest_files.py`

Zrcadlí dvojici `chunk_laws.py` + `dump_chunks.py`:

```bash
uv run scripts/ingest_files.py data/files/*.pdf --dry-run --stats
uv run scripts/ingest_files.py data/files/smlouva.pdf --dump
uv run scripts/ingest_files.py data/files/*.pdf
```

- `--dry-run` — parse + chunk bez Qdrantu a bez embedding API
- `--stats` — token histogram, jako u zákonů
- `--dump` — čitelný výpis chunků do `data/file_chunks/<slug>.chunks.txt`
- bez přepínačů — chunkuje, indexuje do `org_files` a uklidí sirotky

Parsované dokumenty se cachují do `data/parsed/<slug>.docling.json`
(`--no-cache` vypíná), takže sken projde Tesseractem jednou a další běhy
s jiným `--max-tokens` jedou z cache.

## Testování

### Reorganizace `ingestion/`

Jde o přesun bez změny chování, takže důkazem je nezměněný výstup:

```bash
uv run pytest                                                  # baseline před přesunem
uv run scripts/chunk_laws.py data/laws/*.json --out /tmp/before # před
uv run scripts/chunk_laws.py data/laws/*.json --out /tmp/after  # po
diff -r /tmp/before /tmp/after                                  # musí být prázdný
uv run pyright                                                  # odhalí zapomenuté importy
```

Stejný postup jako u přejmenování `Chunk` → `LawChunk`; hlavní riziko je
mechanické (zapomenutý import), a to pyright chytí.

### Nové moduly — bez sítě a bez kontejneru

| test | co ověřuje |
|---|---|
| `test_files_client.py` | přes `httpx.MockTransport`: odeslané options, mapování `status: failure` a timeoutu na `DoclingError` |
| `test_files_chunker.py` | nad malým `DoclingDocument` fixture v `tests/data/`: pole `FileChunk`, determinismus `chunk_id` (dva běhy = identický výstup), přítomnost nadpisů v `text`, a že adaptér vrací stejné počty jako přímo volaný `TokenCounter` |
| `test_indexer.py` (rozšíření) | `prune_orphans` maže právě sirotky a nic jiného; ve stylu stávajících testů |

### Manuální ověření

Síťový integrační test se **nezavádí** — ověření proběhne ručně přes
`scripts/ingest_files.py` nad `data/files/`:

| soubor | co na něm ověřit |
|---|---|
| `smlouva.pdf` | sken bez textové vrstvy → Tesseract a česká diakritika (`ě š č ř ž ý á í é`) |
| `faktura.pdf` | digitální PDF s tabulkou → `table_mode=accurate`, textová vrstva místo OCR |
| `scriptum.pdf` | delší strukturovaný dokument → chunking a nadpisová hierarchie v headeru |

Vedle toho Gradio UI na `:5001/ui` pro vizuální kontrolu parsovaného výstupu.

## Nové závislosti

- `httpx` — HTTP klient
- `docling-core` — `DoclingDocument` a `HybridChunker`

`transformers` se **nepřidává**; exact tokenizer zůstává volitelný, jak je
dnes u zákonů.

## Rizika

**API docling-serve se mezi verzemi mění.** Přepínač OCR enginu se přejmenoval
(`ocr_engine` → `ocr_preset` se server-side policy `allowed_ocr_presets`).
Mitigace: přesná jména polí se ověří proti `/openapi.json` běžícího kontejneru,
ne podle dokumentace, a image se v compose připne na konkrétní tag.

**Tesseract v base image.** Není jisté, že postačí doinstalovat langpack —
může být potřeba i `tesserocr`. Mitigace: první krok implementace je postavit
image a ověřit český OCR výstup, teprve pak se píše klient.

**Rychlost OCR na M1 CPU.** Sken se OCRuje řádově sekundy na stránku.
Mitigace: parse cache a `DOCLING_SERVE_MAX_SYNC_WAIT=600`.

## Mimo rozsah

- `user_files`, session, TTL a upload endpoint
- HTTP API / web UI pro nahrávání
- Role-based filtrace nad `org_files` ([[project-spec]], otevřené rozhodnutí)
- Jakákoli změna chunkingu zákonů nebo Qdrant schématu — tenhle design
  nevynucuje reindexaci existujících dat
- Enrichment funkce Doclingu (popisy obrázků, vzorce, kód)
