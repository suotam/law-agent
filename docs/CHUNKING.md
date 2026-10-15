# Chunkování zákonů pro RAG

`law_agent.ingestion.laws` převádí zákony z API [ceskezakony.cz](https://ceskezakony.cz)
na chunky připravené k embedování. Funguje na libovolném českém předpisu — od
357fragmentového zákona bez hlav po 3000fragmentový zákoník s přílohami.

```python
from law_agent.ingestion.laws import LawChunker, LawDocument, validate

document = LawDocument.from_json("zakon.json")
chunks = LawChunker().chunk(document)

print(validate(document, chunks).describe())
```

## Princip

**Kotvou je paragraf, protože paragraf je to, co se cituje.**

1. **Vejde se § do rozpočtu?** → jeden chunk. Při `max_tokens=768` sem spadá
   ~90 % paragrafů.
2. **Nevejde?** → dělí se po vlastní struktuře: odstavce → písmena → body.
   Rekurze nezná tvar zákona, jde prostě o úroveň níž.
3. **Každý podřízený chunk opakuje uvozující text rodiče.** Bez toho je
   `a) pozbyl-li zaměstnanec…` nesmysl — chybí mu `(1) Zaměstnavatel je povinen
   převést zaměstnance na jinou práci`.
4. **Ani jeden list se nevejde?** → až tehdy dělení po větách s překryvem
   (regex respektuje zkratky `odst.`, `písm.`, `Sb.`, … — naivní dělení po tečce
   by rozsekalo každou citaci).
5. **Krátké sousední §§ se slučují**, ale jen když ani jeden nemá vlastní nadpis.
   Nadpisem vždy začíná nový chunk: `§ 41 – Převedení na jinou práci` je
   samostatné téma, a sloučení by do jednoho vektoru nacpalo tři nesouvisející
   normy, do jejichž průměru by se pak trefoval každý dotaz.

## Kontextová hlavička

Ke každému chunku se připojuje hlavička, která se **embeduje spolu s textem** —
tělo často neobsahuje ani název zákona, ani to, čeho se týká:

```
zákon č. 262/2006 Sb. – zákoník práce (znění k 2026-01-01)
ČÁST DRUHÁ – PRACOVNÍ POMĚR > HLAVA III – ZMĚNY PRACOVNÍHO POMĚRU
§ 41 – Převedení na jinou práci, odst. 1 písm. a) až c) (část 1/2)
```

`chunk.text` = hlavička + tělo (jde do embeddingu), `chunk.body` = jen tělo
(ukazuje se uživateli).

## Konfigurace

```python
ChunkingConfig(
    max_tokens=768,  # strop chunku včetně hlavičky
    min_tokens=120,  # pod tím kandidát na sloučení
    hard_max_tokens=8192,  # limit embedding modelu (kontroluje validace)
    merge_small_sections=True,
    include_frontmatter=False,  # preambule a podpisy
    include_annexes=True,
    footnote_mode=FootnoteMode.METADATA,  # METADATA | INLINE | SEPARATE | IGNORE
    overlap_sentences=1,
    include_breadcrumb_header=True,
    namespace="laws",
)
```

**Proč 768?** Kalibrováno na datech: 430 paragrafů zákoníku práce má medián
~220 tokenů, p90 ~650. Při 768 zůstává ~90 % paragrafů vcelku. Menší hodnoty
(256–512) zvyšují přesnost zásahu za cenu roztříštění kontextu, větší rozmělňují
embedding.

**Počítání tokenů** — výchozí `HeuristicTokenCounter` odhaduje 3,0 znaku na
token, což je pro češtinu pod XLM-RoBERTa (reálně 3,2–3,6) záměrně podstřelené:
odhad nadhodnocuje, takže chunky zůstávají pod skutečným limitem. Pro přesné
rozpočtování stačí podstrčit skutečný tokenizér (vyžaduje `transformers`, který
není závislostí projektu):

```python
from law_agent.ingestion import HuggingFaceTokenCounter
from law_agent.ingestion.laws import LawChunker

chunker = LawChunker(token_counter=HuggingFaceTokenCounter("BAAI/bge-m3"))
```

## Výstup

`LawChunk` nese text, citaci a provenienci; `chunk.to_payload()` z něj udělá
plochý dict pro vektorovou DB. Podstatná pole:

| pole | k čemu |
|---|---|
| `text` / `body` | co se embeduje / co se ukazuje |
| `citation`, `section` | `§ 41 odst. 1 písm. a) až c) zákon č. 262/2006 Sb.` |
| `chunk_id` | **nezávislé na obsahu** → novelizace aktualizuje tytéž řádky místo duplikace |
| `point_id` | UUIDv5, přímo použitelné jako Qdrant point id |
| `content_hash` | hash textu → re-ingest přeskočí nezměněné chunky |
| `breadcrumb`, `group_heading` | strukturální kontext |
| `source_fragment_ids`, `position_start/end` | provenience, řazení, rozšíření na sousedy |
| `is_effective`, `is_repealed`, `is_amended` | filtry při dotazu |
| `footnotes` | `{"1)": "Směrnice Rady 98/59/ES…"}` |

Poznámka k retrievalu: právní dotazy jsou často doslovné (`„§ 52 písm. c)"`),
takže samotné dense hledání je míjí — proto hybridní režim, dense + sparse nad
týmž `text`.

## Provoz

```bash
uv run scripts/chunk_laws.py data/laws/*.json --stats
uv run scripts/chunk_laws.py data/laws/zakon.json --out data/chunks --max-tokens 512
uv run scripts/chunk_laws.py data/laws/zakon.json --sample 3
```

Skript končí nenulovým kódem, když neprojde validace — použitelné v CI.

`validate(document, chunks, config)` hlídá čtyři invarianty: **pokrytí** (každý
indexovatelný fragment je aspoň v jednom chunku — tohle odhalí, že nový tvar
zákona tiše polyká obsah), **velikost**, **unikátní `chunk_id`** a že žádný
chunk není jen hlavička.

Naměřeno ve výchozí konfiguraci:

| | 106/1999 | 262/2006 |
|---|---|---|
| fragmentů / paragrafů | 357 / 41 | 3027 / 431 |
| chunků | 46 | 426 |
| sloučených §§ | 2 | 69 |
| dělení po větách | 0 | 3 |
| tokeny min / p50 / p90 / max | 68 / 416 / 671 / 746 | 101 / 382 / 679 / 752 |
| pokrytí / přes limit | 100 % / 0 | 100 % / 0 |

## Přidání nového zákona

1. Stáhnout fragmenty (`scripts/download_fragments.py`) do `data/laws/`.
2. `uv run scripts/chunk_laws.py data/laws/novy_zakon.json --stats` —
   zkontrolovat `coverage=100%`, `oversized=0`, prázdné `unknown types`.
3. Objeví-li se neznámý typ, zařadit ho do `_EXPLICIT` v `laws/taxonomy.py`.
   Do té doby ho řeší tvarový fallback, takže se text neztrácí.
4. Přidat soubor do `REAL_LAWS` v `tests/conftest.py` kvůli regresním testům.

## Proč parser vypadá, jak vypadá

Tři vlastnosti vstupních dat, které nejsou v dokumentaci API a určily celý návrh
— bez nich vypadá `laws/document.py` zbytečně složitě:

1. **`parent_fragment_id` je vždy `null`.** Rodičovství se musí rekonstruovat.
2. **`depth` a cesta ve `fragment_id` si odporují.** Obaly `Block_*` nejsou
   prefixem cesty toho, co obalují: odstavec je podle `depth` potomkem bloku, ale
   podle cesty jeho sourozencem. Strom se proto staví ze stacku podle `depth`
   a `position`; `fragment_id` slouží jen k identitě a k odvození druhu jednotky
   pro citaci (`par_41` → `§ 41`, `odst_1` → `odst. 1`).
3. **`depth` téhož typu se mezi zákony liší** — `Paragraf` má depth 4 v zákoníku
   práce a 3 v zákoně 106/1999. Žádná logika se proto nesmí vázat na konkrétní
   číslo `depth`.

Z téhož důvodu se fragmenty neklasifikují podle `type` (otevřený slovník, mezi
zákony se liší), ale podle **role** (`laws/taxonomy.py`): `SECTION` je kotva,
`TEXT` tělo, `CONTAINER` seskupení, dál `HEADING`, `FOOTNOTE`, `DOC_META`, `SKIP`.
Neznámé typy se klasifikují podle tvaru (prázdný `content` s potomky →
`CONTAINER`, cokoli s textem → `TEXT`), takže se text nikdy nezahodí — a zároveň
se počítají v `document.report.unknown_types`, aby na sebe upozornily.
