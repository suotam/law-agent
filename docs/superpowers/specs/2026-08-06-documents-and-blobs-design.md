# Dokumenty, složky a blob store

_Spec, 2026-08-06. Nahrazuje první polovinu `2026-08-05-persistence-layer-design.md`._

Druhá polovina původního specu žije v `2026-08-06-conversation-archive-design.md`, který na
tomhle staví.

## Kontext

Projekt má dnes jediné úložiště — Qdrant. Ingest zákonů i souborů z CLI funguje, hybridní
retrieval funguje, jednoduchý RAG chain se streamem a testovací UI také, ale nic mimo vektory
se neuchovává.

Blokátor je identita dokumentu. Dnes je `doc_id` cesta relativně k ingestion rootu
(`scripts/ingest_files.py:doc_id_for`). Jakmile soubor přijde z uploadu ve webovém UI, žádná
cesta neexistuje a identita se rozpadne — bez toho nelze postavit upload, a tedy ani stránku
pro správu org files. Druhá potřeba je originál souboru: bez něj nevede proklik z citace na
původní PDF.

Roadmapa směřuje na správu org files se složkami a přístupem podle rolí. Tenhle spec staví
schéma, blob store a strom složek; ACL a auth přijdou později, ale tvar se fixuje tady.

**Existující data v Qdrantu se zahazují a ingestují znovu.** Přechod `doc_id` z cesty na uuid
se tím přestává řešit jako migrace — testovacích dokumentů je pár.

## Rozhodnutí

| Otázka | Volba | Proč |
|---|---|---|
| Relační DB | **Postgres** v docker compose | Souběžné zápisy z webového UI a role-based filtrace jsou na roadmapě |
| Ovladač DB | **Sync SQLAlchemy 2.0** | Požadavku dominuje LLM stream; Qdrant, embeddingy i BM25 jsou sync |
| Modely | **ORM entita ≠ Pydantic model** | ORM zůstává v `db/`, repozitář vrací ven Pydantic |
| Migrace schématu | **Alembic** | Schéma se bude měnit s každým krokem roadmapy |
| Blob store | **Souborový systém** za rozhraním `BlobStore` | Docker volume, záloha = tar adresáře; rozhraní umožní pozdější výměnu za S3 |
| Identita dokumentu | **uuid vlastněné databází** | Cesta na disku po uploadu neexistuje |
| Mazání dokumentu | **Hard delete** | Uživatel maže záměrně; soft delete by držel blob, který nejde obnovit |
| Zákony | **Bez tabulky a bez blobu** | Payload law chunku už nese vše pro odkaz i plnou citaci |
| `uploaded_by` | **Textový sloupec**, `users` až s auth | Povýšení na FK je jedna migrace |

## Blob store

Obsahově adresovaný: soubor se ukládá pod `sha256` svého obsahu, cesta
`data/blobs/ab/cd/abcd…`. Deduplikace zadarmo, immutabilní obsah — dvakrát nahraná stejná
smlouva nezabere dvakrát místo.

Rozhraní `BlobStore`: `put(bytes) -> sha256`, `open(sha256)`, `exists(sha256)`,
`delete(sha256)`. Jediná implementace `FilesystemBlobStore`.

Ukládají se **jen originály nahraných souborů**. Ne zákony (nemají binární originál na naší
straně) a ne naparsovaný Docling JSON.

`put()` u už existujícího blobu udělá `touch` — viz GC sweep níže.

## Schéma

```
folders          id (uuid), parent_id (fk, nullable), name (text),
                 created_at

documents        id (uuid, = doc_id), namespace (text), folder_id (fk, nullable),
                 message_id (fk, nullable),
                 filename, mime, byte_size, blob_sha256,
                 uploaded_by (text), uploaded_at,
                 status, error, chunk_count, indexed_at
```

```sql
CREATE UNIQUE INDEX ux_folders_sibling_name ON folders (parent_id, name);
CREATE UNIQUE INDEX ux_folders_root_name    ON folders (name) WHERE parent_id IS NULL;
CREATE UNIQUE INDEX ux_documents_folder_blob ON documents (folder_id, blob_sha256);
```

**Strom složek má víc kořenů.** „Smlouvy", „Faktury", „Vzory" leží vedle sebe, každá
s `parent_id = NULL`; žádný umělý root řádek neexistuje. Proto dva unique indexy místo
jednoho: v Postgresu se NULL nerovná NULL, takže `(parent_id, name)` samo o sobě dvě kořenové
„Smlouvy" nezakáže.

**`documents.id` je `doc_id`** používané v Qdrant payloadu a ve `scope` pro `prune_orphans`.
Tím je identita jedna napříč oběma úložišti.

**Dvě vzájemně se vylučující umístění dokumentu.** Org file má `folder_id` a `message_id`
NULL; in-chat soubor naopak (jeho polovinu popisuje spec o archivu konverzací). Právě jedno
z nich je vyplněné — kontroluje aplikační vrstva.

**`namespace` zůstává sloupcem**, i když ho lze z těch dvou odvodit: je to totéž, co jde do
payloadu chunku, a čtenář ho má mít po ruce bez odvozování.

**Duplicitní obsah.** `UNIQUE (folder_id, blob_sha256)` odmítne tentýž soubor dvakrát v jedné
složce — to je vždy omyl. Napříč složkami je duplicita povolená a záměrná: vzorová smlouva
může být ve „Vzory" i v klientské složce, u org files je složka součástí významu a citace
„Vzory / Smlouva" a „Klient A / Smlouva" nesou pro právníka různou informaci. Vektory se
v takovém případě **nesdílejí** — dva řádky, dvě uuid, dvě sady bodů. UI při uploadu
upozorní, že obsah už je nahraný jinde, a nechá uživatele pokračovat.

**Stav ingestu** jsou sloupce na `documents`, ne vlastní tabulka historie: UI potřebuje
„prošlo / neprošlo a proč", ne časovou řadu pokusů. `status` a `namespace` jsou `text`,
validované v Pythonu přes `StrEnum` — přidání hodnoty pak není migrace.

## Přístup podle rolí (mimo rozsah, tvar se fixuje teď)

ACL se nestaví, dokud není auth. Tvar, kterým se půjde, aby se schéma nemuselo předělat:

- práva visí na složce a **dědí se dolů** na podsložky a soubory; výjimka na konkrétní soubor
  je jeden ACL řádek navíc
- do **payloadu chunku jde `folder_id`**, ne seznam rolí
- autorizace se rozřeší v Postgresu z uživatelových rolí na množinu povolených `folder_id` —
  desítky hodnot — a ta jde do `extra_filter` retrievalu

Kdyby v payloadu byly role, každá změna oprávnění by přepisovala payloady všech dotčených
chunků. Takhle je změna práv řádek v ACL a přesun dokumentu je `set_payload` na chunky
jednoho dokumentu.

## Aplikační vrstva

```python
def ingest_document(
    data: bytes, *, filename: str, folder_id: UUID | None = None, message_id: UUID | None = None
) -> UUID
```

Jedna funkce pro CLI i pro budoucí upload ve webovém UI. Vyžaduje právě jedno z `folder_id`
/ `message_id`.

**Upload dokumentu**

1. `BlobStore.put(data)` → `sha256`
2. INSERT `documents` (status `pending`); `id` je nové `doc_id`
3. `DoclingClient.parse` → `FileChunker.chunk(document, doc_id=str(id))`
4. `index_chunks` → `prune_orphans`
5. UPDATE status `indexed`, `chunk_count`, `indexed_at`; při chybě status `failed` + `error`

**Smazání dokumentu**

1. `prune_orphans(scope={"namespace": …, "doc_id": …}, keep=[])` — existující funkce
   v `src/law_agent/indexing/indexer.py`
2. `DELETE` řádku
3. `BlobStore.delete`, pokud na `blob_sha256` neukazuje jiný řádek

Pořadí je záměrné: kdyby `DELETE` řádku předcházel úklidu vektorů, pád procesu mezi tím by
nechal v Qdrantu body bez jakékoli stopy v databázi.

**GC sweep blobů**

Pojistka proti pádu procesu mezi `put()` a `INSERT`, ne hlavní cesta mazání. Pro každý blob
na disku:

```sql
SELECT count(*) FROM documents WHERE blob_sha256 = ?
```

a smaže ty bez reference. Reference se nepočítá do sloupce — počítadlo driftuje při pádu
procesu, kdežto `documents` je referenční index sám o sobě.

**Grace period.** Sweep uvažuje jen bloby s `mtime` starším než 24 hodin; `put()` u už
existujícího blobu dělá `touch`. Bez toho zůstává okno mezi `SELECT count(*)` → 0 a `unlink`,
ve kterém jiný uživatel nahraje tentýž soubor, deduplikovaný `put()` nic nezapíše a sweep
smaže blob živého dokumentu. Projevilo by se to ztrátou dat, ne chybou.

## CLI ingest

`scripts/ingest_files.py` je vývojářský nástroj a zůstává **jen na org files**. Vlastní kód
nemá — tělo dnešní smyčky se stěhuje do `ingest_document`, skript je argparse, přečtení
souboru a volání té funkce.

```
uv run scripts/ingest_files.py data/files/*.pdf --folder Vzory
```

- `--root` a `doc_id_for` mizí; identita je uuid řádku
- `--folder` je nový a povinný, `--name` nepovinný (výchozí je jméno souboru)
- `--folder` bere cestu (`Vzory/Smlouvy`) a **neexistující složky založí** — je to vývojářský
  nástroj, ne správa struktury; ve webovém UI se složky zakládají výslovně
- `--dry-run`, `--stats`, `--dump`, `--cache-dir`, `--no-cache` zůstávají a databáze se
  netýkají: zastaví se na parse a chunk, přesně jak to dělají dnes
- druhý běh nad stejným adresářem nic nezduplikuje — `UNIQUE (folder_id, blob_sha256)`
  nezměněné soubory odmítne a skript je vypíše jako přeskočené; změněný soubor má jiný hash
  a založí nový dokument, ten starý se smaže ve správě org files

## Balíčky

- `src/law_agent/storage/` — `BlobStore` protokol, `FilesystemBlobStore`, GC sweep
- `src/law_agent/db/` — engine/session, ORM modely, repozitáře
- `src/law_agent/documents/` — `ingest_document`, Pydantic doména dokumentu a složky

`ingestion/`, `indexing/` a `retrieval/` o databázi nevědí — dostávají stávající kontrakty
(`ChunkLike`, `index_chunks`, `prune_orphans`).

## Testy

Většina se obejde bez databáze:

- **blob store** — round-trip, deduplikace, sweep nesmí smazat sdílený blob ani blob mladší
  než grace period

S databází:

1. `alembic upgrade head` projde na čistou databázi
2. `UNIQUE (folder_id, blob_sha256)` odmítne druhý týž soubor ve složce a povolí ho v jiné
3. dvě kořenové složky téhož jména se odmítnou; dvě stejnojmenné pod různými rodiči projdou
4. `ingest_document` bez `folder_id` i `message_id` (a s oběma) selže

Že SQLAlchemy vloží řádek, se netestuje.

**Jak.** Session fixture vytvoří na běžícím compose Postgresu databázi `law_agent_test`,
pustí `alembic upgrade head` a na konci ji dropne. Každý test běží ve vnější transakci
rollbacknuté na konci; aby to nerozbily repozitáře volající vlastní `commit()`, session se
váže s `join_transaction_mode="create_savepoint"` (SQLAlchemy 2.0). Když databáze neběží,
modul se **skipne**, stejným vzorem jako `tests/conftest.py:83` u chybějících vzorků zákonů.

Žádné testcontainers (compose už běží, projekt nemá CI) a žádné SQLite — testoval bys jinou
databázi, než na které to poběží: bez `jsonb`, bez částečných indexů, s jinou sémantikou
transakcí.

## Dotčené soubory

**Nové**

- `src/law_agent/storage/blobs.py`, `src/law_agent/storage/gc.py`
- `src/law_agent/db/{engine,models,repositories}.py`
- `src/law_agent/documents/{models,service}.py`
- `alembic/` + první migrace
- `tests/test_blobs.py`, `tests/test_blob_gc.py`, `tests/test_documents.py`

**Měněné**

- `docker-compose.yml` — služba `postgres`, volume `postgres_data`, volume pro bloby
- `src/law_agent/config.py` — `database_url`, `blob_root`
- `pyproject.toml` — `sqlalchemy>=2`, `alembic`, `psycopg[binary]` (přes `uv add`)
- `scripts/ingest_files.py` — tělo smyčky do `ingest_document`, `--folder` místo `--root`
- `src/law_agent/ingestion/files/models.py` — docstring u `doc_id` přestává platit
  („path relative to the ingestion root"); `folder_id` do payloadu
- `src/law_agent/ingestion/files/chunker.py` — `folder_id` do payloadu, když je přítomný

## Mimo rozsah

- **ACL a `users` tabulka** — až s auth; `uploaded_by` je zatím text
- **UI pro správu org files** — vlastní krok, tenhle spec staví schéma pod ním
- **Async ovladač**
- **Ukládání naparsovaného Docling JSON** — odvozená data; agent si širší kontext dnes
  přečte z Qdrantu (chunky nesou `doc_id`, `chunk_index`, `chunk_total`, takže scroll
  s filtrem seřazený podle indexu vrátí sousedy i celý dokument). Přidání později je sloupec
  plus backfill přeparsováním originálů, které v blob store jsou. `data/parsed/` zůstává jako
  vývojářská cache pro CLI.
- **Tabulka zákonů a jejich bloby** — payload law chunku
  (`src/law_agent/ingestion/laws/models.py:209`) už nese `law_id`, `law_number`, `law_year`,
  `law_title`, `law_version_date`, `law_citation` i `anchor_fragment_id`. Společná tabulka
  s `documents` by měla polovinu sloupců vždy NULL: zákony mají identitu `law_id` ne uuid,
  vznikají stažením z API ne uploadem, nemají binární originál ani nahrávajícího uživatele,
  zato mají verzování podle znění k datu. Tabulka `laws` vznikne, až bude mít co držet, co
  v payloadu není.
- **Logování a audit trail** — až s agent loopem (Langfuse self-hosted) a s auth

## Ověření

- `docker compose up -d postgres && uv run alembic upgrade head` — migrace projde na čistou
  databázi
- `uv run pytest` — blob store, sweep, repozitáře
- `uv run scripts/ingest_files.py data/files/*.pdf --folder Vzory` — dokumenty dostanou uuid
  `doc_id`, řádek v `documents` se statusem `indexed` a odpovídajícím `chunk_count`
- druhý běh téhož příkazu — soubory přeskočené, v `documents` nepřibyl řádek, v `data/blobs`
  leží jeden soubor bez duplikátu
- tentýž soubor s `--folder Klienti` — nový řádek, nové uuid, blob na disku pořád jeden
- `uv run scripts/query_files.py "<dotaz>"` — retrieval vrací citace beze změny chování
- ruční kontrola: `documents.id` odpovídá `doc_id` v payloadu Qdrant bodu a `folder_id` tam je
- smazání dokumentu — vektory zmizí, blob zmizí; při dvou dokumentech sdílejících blob
  smazání jednoho blob nechá
