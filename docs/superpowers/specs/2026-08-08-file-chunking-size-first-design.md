# Chunkování souborů: velikost rozhoduje, struktura radí

_Spec, 2026-08-08. Nahrazuje chunkovací část `2026-08-04-docling-ingestion-design.md`._

Týká se jen namespace `org_files` a in-chat příloh, tedy `law_agent.ingestion.files`. Zákony
mají vlastní chunker (`ingestion/laws/chunker.py`) a ten se nemění.

## Problém

Docling u PDF nadpisy pozná, ale nedá jim úrovně — hierarchie ve vstupu neexistuje.
`HybridChunker` přitom nadpis z těla vyjme a udělá z něj metadata. Tím se detekce nadpisu
stává nosnou: každá chyba stojí buď rozbitý chunk, nebo ztracený kontext.

Konkrétně:

- **Ploché úrovně přepisují breadcrumb.** Všechny nadpisy mají stejnou úroveň, takže každý
  další přepíše předchozí místo aby se vnořil.
- **Falešný nadpis tříští text.** Cokoli, co Docling omylem označí za nadpis, způsobí řez.
- **Řez na každém nadpisu dělá malé chunky.** U dokumentu s hustými nadpisy vycházejí chunky
  na třetinu budgetu — retrieval pak vrací útržky.

Společná příčina: strukturu rozhoduje, velikost jen dorovnává.

## Řešení

Otočit ten vztah. **Velikost rozhoduje, struktura jen radí, kde řezat.** Nadpis zůstává v těle
chunku jako obyčejný text. Tím přestává být jeho detekce nosná — špatně rozpoznaný nadpis
nanejvýš posune řez o odstavec. Struktura se z rozhodnutí stává heuristikou, a heuristika smí
být nespolehlivá.

Dokument je plochý proud položek v pořadí čtení, ne strom. Odpadá rekurze i úrovně, tabulka je
jen položka s jiným serializerem, a provenience stránek zůstává (na rozdíl od cesty přes
markdown, kde by se ztratila).

## Rozhodnutí

| Otázka                      | Volba                                    | Proč                                                                          |
| --------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------- |
| Vztah struktury a velikosti | **Velikost rozhoduje**                   | Detekce nadpisu přestává být nosná                                            |
| Nadpisy                     | **Zůstávají v těle** chunku              | Chybná detekce posune řez, nerozbije text                                     |
| Kdy řezat dřív              | **Nad měkkým prahem na nadpisu**         | Jediná hranice, která je silnější než konec odstavce                          |
| Vážení síly hranic          | **Není**                                 | Položky _jsou_ odstavce, každý řez mezi nimi je automaticky na konci odstavce |
| Překryv                     | **Žádný**                                | Chunky zůstanou disjunktní; léčba symptomu, který u budgetu 768 nemusí nastat |
| Nadrozměrná položka         | **Dělí se podle typu**                   | Text po větách, tabulka po řádcích s opakovanou hlavičkou                     |
| Seznam                      | **Po odrážkách**, hranice bez síly       | Zůstane vcelku když se vejde, rozdělí se rozumně když ne                      |
| `headings`                  | **Poslední viděný nadpis**, jednoprvkový | Hierarchie ve vstupu neexistuje, trail se nemá z čeho postavit                |
| `header` na modelu          | **Zaniká**                               | Nadpis je v těle, prefix není z čeho stavět                                   |
| `body` na modelu            | **Zaniká**                               | Rovnalo by se `text` a nikdo ho nečte                                         |

## Algoritmus

1. Z `DoclingDocument` udělej seznam kusů textu v pořadí čtení. Nadpis je taky jen kus textu.
2. Lep kusy za sebe do chunku.
3. Je-li chunk už nad měkkým prahem a další kus je nadpis → uřízni před ním.
4. Nevejde-li se další kus do budgetu → uřízni.
5. Kus, který se sám nevejde nikam, rozsekej: text po větách, tabulku po řádcích.

Díly z bodu 5 nejdou ven jako hotové chunky. Ven jdou jen ty, které naplnily budget; **poslední
díl zůstává otevřený a lepí se na něj další položky.** Jinak by za každou velkou tabulkou
vznikl krátký zbytkový chunk — přesně ten druh malého chunku, který tenhle spec ruší.

Dvě čísla na ladění: **budget** (dnes 768 tokenů, `DEFAULT_MAX_TOKENS`) a **měkký práh**
(výchozí 60 % budgetu). Obojí parametrem konstruktoru, aby šlo ladit z testu.

## Proud položek

Vstup je `document.iterate_items()` zploštělý na seznam. Do proudu nejdou:

- `page_header`, `page_footer` — opakovaly by se v každém chunku a kazily embedding
- obrázky bez popisku — nemají co embeddovat

Vyloučené typy jsou **jeden explicitní seznam** na jednom místě, ne podmínky rozeseté po kódu.

Seznam se rozpadá na jednotlivé odrážky. Hranice mezi odrážkami nemá sílu nadpisu, takže bod 3
se na ní neuplatní — seznam se rozdělí až na budgetu. Tím zůstane vcelku, kdykoli se vejde, a
nepotřebuje vlastní dělící logiku.

## Serializace položky

Každý typ položky má serializer `položka → text`. Nadpis se serializuje včetně markdown
prefixu (`## Odstoupení od smlouvy`), aby v těle chunku šel poznat jako nadpis.

Dva typy umí navíc **rozdělit samy sebe**, když se nevejdou do budgetu:

- **text** — po větách (dnešní chování `semchunk`)
- **tabulka** — po řádcích, a **hlavička se opakuje do každého dílu**. Bez toho je druhý díl
  jen holé řádky bez významu sloupců.

Ostatní typy (nadpis, popisek, odrážka) jsou krátké a v praxi se vejdou vždy; fallback pro ně
je dělení po větách.

## Nadpisy a citace

Model má dvě podobně pojmenovaná pole a je potřeba je nesplést:

- **`headings`** — metadata, ze kterých se skládá citace. **Zůstává.**
- **`header`** — text, který `HybridChunker` lepil *před* tělo, aby se nadpis embedoval
  (`text == header + body`). **Zaniká**, protože nadpis je nově rovnou v těle.

Při procházení proudu se drží jedna proměnná: **poslední nadpis, který jsem viděl**. Přepisuje
se pokaždé, když v proudu přijde nadpis. Při uzavření chunku se přečte a uloží do `headings`.

Z jednoho pravidla vyjdou oba případy:

- Chunk nadpisy obsahuje → dostane ten poslední z nich (proměnná se během něj přepsala).
- Chunk žádný nadpis neobsahuje (vznikl tvrdým řezem uprostřed sekce) → dostane nadpis
  z předchozího chunku, protože se proměnná nepřepsala.

`headings` zůstává `list[str]` s nula nebo jednou položkou. `render_citation` ani payload se
nemění, `headings[-1]` funguje dál.

Nadpis je tedy na dvou místech — v těle chunku (kde se embedduje) a v `headings` (odkud se
skládá citace). Je to záměr: **selže-li detekce nadpisu, citace dostane horší popisek, ale text
chunku zůstane celý a správný.** To je celý smysl téhle změny.

## Dopad na model

`FileChunk.header` i `FileChunk.body` zanikají. Tím zaniká invariant `text == header + body`
i pomocná funkce `_header_of`; zbývá jediné textové pole `text`.

`body` padá proto, že by nadále nesl tutéž hodnotu jako `text` a **nikdo ho nečte** — indexing
i retrieval sahají výhradně po `text`, v payloadu byl jen setrvačností. `LawChunk.body`
zůstává; tam prefix pořád existuje a pole má obsah.

Vše ostatní na `FileChunk` je beze změny: identita (`chunk_id`, `point_id`), `content_hash`,
`pages`, `citation`, `chunk_index`/`chunk_total`, `token_count`, `char_count`.

Dopad sahá i mimo chunker: `FileChunk.create()` ztrácí parametry `header` a `body`, payload
ztrácí klíč `body` a **docstringy polí `text` a `headings` přestávají platit** (`text` už není
„heading context + body", `headings` už není trail, ale poslední viděný nadpis). Položka
proudu musí nést provenienci stránek, jinak Balič nemá z čeho složit `pages`.

## Struktura kódu

`FileChunker` přestává být obalem `HybridChunker` a rozpadá se na tři jednotky, každou
testovatelnou zvlášť:

| Jednotka          | Zodpovědnost               | Vstup → výstup                               |
| ----------------- | -------------------------- | -------------------------------------------- |
| **Proud položek** | Zploštění a filtr          | `DoclingDocument` → `list[Item]`             |
| **Serializace**   | Text položky a její dělení | `Item` → `str`, `Item, budget` → `list[str]` |
| **Balič**         | Body 2–4 algoritmu         | `list[Item]` → `list[Chunk]`                 |

`FileChunker` zůstává tenkou vrstvou: zavolá je v pořadí a namapuje výsledek na `FileChunk`.
Metoda `chunk()` má stejnou signaturu jako dnes, takže volající (`documents/service.py`,
`scripts/ingest_files.py`) se nemění. Mění se konstruktor: mizí `merge_peers` (byl to parametr
`HybridChunkeru`), přibývá měkký práh. Oba volající posílají jen `max_tokens`, takže se jich to
netýká.

`TokenCounterTokenizer` zaniká spolu s `HybridChunkerem` — adaptér na Docling API už není
komu podat. Počítání tokenů jde napřímo přes `TokenCounter`.

## Testování

Testy jdou po jednotkách, ne přes celý chunker:

- **Proud** — vyloučené typy nejsou ve výstupu; pořadí odpovídá pořadí čtení; seznam se
  rozpadl na odrážky.
- **Serializace** — nadpis nese markdown prefix; nadrozměrný text se dělí po větách;
  nadrozměrná tabulka se dělí po řádcích a **každý díl začíná hlavičkou**.
- **Balič** — žádný chunk nepřeteče budget; pod měkkým prahem se na nadpisu neřeže; nad ním
  ano; dokument bez nadpisů dá chunky blízko budgetu.
- **Nadpisy** — chunk s nadpisem dostane ten poslední z nich; chunk bez nadpisu zdědí ten
  předchozí.

Ze stávajícího `tests/test_files_chunker.py` zůstávají v platnosti testy identity,
determinismu, `folder_id`, `conversation_id`, indexů a monotonie budgetu. Ruší se
`test_body_excludes_the_header` a `test_tokenizer_adapter_matches_the_wrapped_counter`.
`test_embedded_text_carries_heading_context` se přeformuluje: nadpis se nově hledá v těle, ne
v prefixu.

`tests/test_files_models.py` a `tests/factories.py` stavějí `FileChunk` s `header` a `body`;
obojí ze staveb vypadává.

Chování nad reálnými PDF se ověřuje ručně mimo test suite.

## Migrace dat

Chunkování se mění od základu, takže se **oba souborové namespace vyprázdní**: `org_files`
i `user_files`. Inkrementální update nemá co zachránit — `chunk_id` je odvozený od indexu a ten
se posune u všeho.

Po vyprázdnění se **firemní soubory ingestují znovu z `data/files`**. In-chat přílohy
(`user_files`) se neobnovují: patří k proběhlým konverzacím a originály pro ně mimo blob store
nejsou.

Smazat je potřeba **obojí — body v Qdrantu i řádky v `documents`.** Ingestní skript odmítá
soubor, jehož obsah už v databázi je (`DuplicateDocumentError`), takže při ponechaných řádcích
by reingest všechno přeskočil a index by zůstal prázdný. Osiřelé bloby uklidí GC.
