# Archiv konverzací a retrieval jako tool call

_Spec, 2026-08-06. Nahrazuje druhou polovinu `2026-08-05-persistence-layer-design.md`._

Staví na `2026-08-06-documents-and-blobs-design.md` — odtud bere Postgres, engine, session,
Alembic, testovací fixture a tabulku `documents`.

## Kontext

Historie chatu dnes žije v `st.session_state` a při refreshi zmizí. Konverzaci musí jít po
týdnu otevřít se zprávami i **funkčními** citacemi — tedy tak, že proklik ze značky `[1]`
pořád vede na ten text, ze kterého odpověď vznikla.

Druhá půlka specu je přestavba chainu. Retrieval je dnes pevný krok před promptem a kontext
se podává system zprávou (`chain/prompt.py:build_messages`). Nově ho **volá model jako
nástroj**, zatím v jednom kole: model vydá `tool_use`, dostane výsledek, odpoví. Bez toho by
archiv ukládal tvar zpráv, který nic nevyrábí, a přechod na agentní smyčku by znamenal
migraci starých konverzací.

Agentní smyčka sama v rozsahu **není**. Schéma i překladová vrstva ji ale musí unést beze
změny — z jednoho kola se stane `while` a nic jiného.

## Rozhodnutí

| Otázka | Volba | Proč |
|---|---|---|
| Kde žije orchestrace | **`src/law_agent/`, ne v UI** | Pořadí „načti historii → model → tool → stream → ulož" musí volat Streamlit i budoucí FastAPI stejně |
| Kdo drží historii | **Server ji čte z DB** | Klient posílá jen nový dotaz; svou kopii má pouze pro render |
| Tvar obsahu zprávy | **`blocks` jsonb, vždy pole** | Nová modalita (reasoning, další nástroj) je nová hodnota v `type`, ne migrace |
| Bloky | **jsonb sloupec, ne tabulka** | Blok nemá vlastní identitu ani životní cyklus, čte se vždy se zprávou |
| Výsledek nástroje | **Samostatný řádek, role `tool`** | Tak to má OpenRouter i LangChain `ToolMessage`; drží pořadí |
| `tool_call_id` | **Uvnitř bloku, ne sloupec** | Nic se na něj nejoinuje — běžící kolo drží smyčka v paměti a staré tool výsledky se modelu nepřehrávají |
| Sloupec `status` | **Neexistuje** | Odpověď se zapisuje až celá; nedokončený dotaz nezanechá rozbitý tvar |
| Sloupec `citations` | **Neexistuje** | Je to `refy v textu ∩ nabídnutá množina` — počítá se při renderu |
| Rozsah `ref` | **Monotónní v rámci jednoho dotazu** | Konverzační čítač by z halucinovaného `[7]` udělal existující, ale cizí citaci |
| Text tool výsledku | **Ukládá se celý** | Nejjednodušší cesta k rekonstrukci archivu; ořezávat se bude, až bude co |
| Argumenty nástroje | **Model dává jen `query`** | Rozsah je volba uživatele a s rolemi i autorizační hranice — ta se modelu do rukou nedává |
| Mazání konverzace | **Soft delete** | Úklid nejde transakčně; omylem smazaná konverzace s klientem je drahá chyba |
| In-chat soubory | **Řádky v `documents`, vázané na zprávu** | Bez originálu vedou citace v archivu do prázdna |

## Schéma

```
conversations    id (uuid), owner (text), title (text), meta (jsonb),
                 deleted_at (nullable), created_at, updated_at

messages         id (uuid), conversation_id (fk), seq (int),
                 role (text), blocks (jsonb), created_at
                 — unique (conversation_id, seq)
```

```sql
CREATE INDEX ix_conversations_owner_updated
    ON conversations (owner, updated_at DESC)
    WHERE deleted_at IS NULL;
```

Index je částečný, protože seznam konverzací smazané nikdy nechce. Zprávy vlastní index
nepotřebují: čtou se vždy celou konverzací, což pokrývá `unique (conversation_id, seq)`.
`seq` přiděluje zápisová transakce jako `MAX(seq) + 1`.

`conversations.meta` drží **výběr zdrojů ze sidebaru** (`scope`, `limit`), aby pokračování
staré konverzace běželo nad stejným rozsahem jako původní. Je to jediný zdroj pravdy —
`ask()` si ho čte, nedostává ho parametrem. Konvence klíčů žije na jednom místě v kódu jako
pydantic model, který se do sloupce serializuje; obecný jsonb má jinak tendenci stát se
skladištěm.

Zprávy `meta` nemají: `model`, `usage` ani `latency` zatím nikdo nečte.

`role` je `text`, ne Postgres enum ani CHECK constraint — validuje se v Pythonu přes
`StrEnum`, aby přidání hodnoty nebyla migrace.

## Zprávy a bloky

Role: `user`, `assistant`, `tool`. `blocks` je **vždy pole**, i pro jediný text — žádné
větvení `str | list` u čtenáře.

```json
{"type": "text",        "text": "…"}
{"type": "reasoning",   "reasoning": "…", "signature": "…"}
{"type": "tool_use",    "id": "call_a1", "name": "search", "args": {"query": "…"}}
{"type": "tool_result", "tool_call_id": "call_a1", "items": [{"ref": 1, …}, …]}
```

- **Žádost o nástroj** je blok `tool_use` uvnitř assistant řádku. Paralelní volání je několik
  `tool_use` bloků v jednom řádku a několik `tool` řádků za ním.
- **Výsledek nástroje** je vlastní řádek s rolí `tool`; `tool_call_id` je uvnitř bloku.
- **Pořadí uvnitř assistant řádku zůstává zachované** — `[reasoning*, text?, tool_use*]`. To
  je právě to, co extended thinking vyžaduje vrátit doslova.

Jeden dotaz uživatele je několik po sobě jdoucích řádků. Na otázku *„Kdy můžu odstoupit od
smlouvy?"*:

| seq | role | blocks |
|---|---|---|
| 1 | `user` | `[text]` |
| 2 | `assistant` | `[reasoning, tool_use call_a1]` |
| 3 | `tool` | `[tool_result call_a1: ref 1, 2, 3]` |
| 4 | `assistant` | `[text: "Do 14 dnů [1], u finančních služeb do 30 [3]."]` |

Model může vedle `tool_use` vrátit i text („Podívám se do zákona…"). Je to skutečný blok,
uloží se a UI ho může ukázat.

S agentní smyčkou přibudou další dvojice řádků 2–3 uvnitř téhož dotazu. Tvar se nemění.

## Retrieval jako nástroj

Jedno kolo, dvě volání modelu:

1. model dostane nástroj `search` a `tool_choice="required"` → vrátí `tool_use`
2. proběhne retrieval, položky dostanou `ref`
3. model dostane výsledek jako `tool` zprávu a `tool_choice="none"` → **streamuje** odpověď

Přechod na smyčku je zahodit ta dvě omezení a obalit to `while`. Schéma, překladová vrstva
ani zápisový tok se tím nemění.

**Nástroj má jediný argument `query`.** `scope` i `limit` doplňuje orchestrace
z `conversations.meta`. Kdyby si rozsah vybíral model, uživatel by vypnul zákony a stejně by
mu z nich přišla odpověď — a s rolemi je rozsah autorizační hranice.

**Formulace dotazu je věc system promptu.** Model si dotaz do retrievalu píše sám, čímž
zadarmo vzniká přeformulování otázky. Sparse půlka hybridního vyhledávání je ale citlivá na
konkrétní slova, takže prompt musí vést k zachování termínů z otázky, ne k abstrahování
(„odstoupení od smlouvy spotřebitel", ne „ukončení závazku"). Při implementaci se výsledky
srovnají s dnešním chováním, kde se hledá doslovný dotaz uživatele.

Kontext se tím stěhuje ze system zprávy do tool výsledku: `chain/prompt.py` je dnes postavený
na opačném předpokladu, `build_messages` mizí a `render_context` se stává vykreslovačem tool
výsledku, číslujícím podle `ref`. Pravidla o značkách zůstávají v system promptu.

## Citace

Značka `[n]` v textu **není pozice v poli, je to `ref`** — odkaz na položku uloženou
v `tool_result` bloku téhož dotazu.

Položka v `tool_result`:

```json
{
  "ref": 1,
  "kind": "law",
  "label": "§ 1829 obč. zák.",
  "content": {"law_id": "…", "anchor": "…", "chunk_id": "…", "text": "Spotřebitel má právo…"}
}
```

Sdílené je `ref`, `kind` a `label`; `content` si tvaruje každý nástroj sám. Dnešní
`Citation.from_chunk` s větvením na namespace se stává překladem retrieval nástroje, web
search bude mít svůj.

**Kdo přiděluje `ref`.** Orchestrace, ve chvíli, kdy překládá výsledek nástroje na položky —
tedy **dřív, než model podklady uvidí**, protože se vypisují do promptu očíslované právě jimi.
Čítač běží přes celý dotaz uživatele: druhé volání v témže dotazu navazuje (`4, 5, …`),
s další otázkou se resetuje na 1. `ref` se **ukládá**, nepočítá se při čtení znovu — je to
záznam toho, co model doopravdy viděl, a nemůže se rozejít, když se později změní pořadí nebo
chunkování.

**Proč ne konverzační čítač.** Po deseti kolech jsou refy `[150]` a model si vymyslí `[7]` —
malá čísla jsou nejpravděpodobnější halucinace. Ta by se rozřešila na existující, ale cizí
citaci z prvního kola, což je horší než nerozřešit nic.

**Rozřešení.** Z řádků s `role = 'tool'` patřících k témuž dotazu se rozbalí `items`
a naindexují podle `ref`. Do jednoho dotazu se počítá to, co ve výpisu leží mezi dvěma `user`
řádky. Všechno nad načtenou konverzací, bez dotazu do Qdrantu.

Seznam citovaných refů se **neukládá** — je to `refy nalezené v textu ∩ refy nabídnuté
v tomhle dotazu`, tedy hodnota odvozená ze dvou věcí, které v načtené konverzaci obě jsou.

**Obrana proti halucinaci:** značka, jejíž `ref` nebyl v tomhle dotazu nabídnut, se zahazuje.
Dnešní `used_indexes` dělá totéž kontrolou rozsahu; nově je to kontrola členství v nabídnuté
množině (`used_refs`).

**Proč ne živé dohledání v Qdrantu.** `chunk_id` je stabilní (`<doc_id>#<index>`, `point_id`
je `uuid5` z něj), ale **stabilní je identita, ne obsah za ní**: reingest editovaného
dokumentu text pod týmž `chunk_id` přepíše, posun hranic chunkování ho přesune jinam
a smazání dokumentu chunk odstraní. Citace v konverzaci z léta by pak tiše ukázala text
z podzimu. Uložený `tool_result` je oproti tomu nehybný, a je to zároveň to, co UI vypisuje
v panelu zdrojů.

**Proklik** rozhoduje `kind` položky:

- `document` → `documents` podle `doc_id` → `blob_sha256` → stream z blob store
- `law` → odkaz na veřejný zdroj sestavený z `law_id` a `anchor`
- další `kind` → vlastní pravidlo daného nástroje (u `web` prostě `url`)

## Překladová vrstva

Jeden modul, dvě funkce: `to_langchain(messages) -> list[BaseMessage]` a
`blocks_from(message: BaseMessage) -> list[dict]`. Je to jediné místo v codebase, které ví,
jak vypadá LangChain zpráva.

Neukládá se serializovaná LangChain zpráva (`messages_to_dict`). Vypadá to jako nulový
překlad, ale přiváže schéma na formát knihovny, který se mezi verzemi mění, a databáze
přestane být čitelná bez LangChainu. LangChain v1 (`langchain>=1.3.14`) zavedl standardizované
content blocks napříč providery; přesný tvar se ověří při implementaci a pravděpodobně
překladovou vrstvu ještě ztenčí, ale uložený tvar zůstává náš.

**Záznam a replay nejsou totéž.** Z historie jdou modelu jen `user` a `assistant` textové
řádky; `tool_use` a `tool_result` z **minulých** dotazů se zahazují. Jinak by se v kontextu
potkalo `[1]` ze tří různých kol a značky by přestaly znamenat cokoli; vedlejší efekt je, že
staré chunky nežerou kontextové okno. V **aktuálním** dotazu naopak tool výsledky modelu jít
musí — bez nich by neměl z čeho odpovědět.

Právě proto může `tool_call_id` být jen v bloku: párování `tool_calls` ↔ výsledek vyžaduje
API jen uvnitř běžícího kola, které drží orchestrace v paměti. Kdyby se to změnilo, sloupec
je jedna migrace.

Poslední pravidlo: **koncový `user` řádek bez odpovědi se modelu neposílá.** Vzniká
u přerušeného dotazu (viz níže) a poslat ho by znamenalo dvě user zprávy za sebou.

`ui/streamlit_app.py:_to_messages` tahle pravidla dnes uplatňuje ručně — přesouvají se do
překladové vrstvy.

## Aplikační vrstva

```python
def create_conversation(owner: str, *, title: str) -> UUID
def ask(conversation_id: UUID, question: str) -> Answer
```

Založení konverzace je vlastní volání, ne `conversation_id: UUID | None` v `ask()` — jinak by
`ask()` mělo dvě chování podle jednoho argumentu a volající by stejně musel vzniklé id dostat
zpátky. `title` se odvodí ze zkrácené první otázky; generování názvu modelem je pozdější
přístavba.

`Answer` má **položky `tool_result` dostupné hned** — UI je potřebuje před prvním tokenem pro
panel zdrojů — a `__iter__` produkující text.

Zápisový tok:

1. `user` řádek → INSERT **hned**, před voláním modelu. Padlý dotaz musí nechat otázku vidět.
2. historie pro model se **čte z DB**, ne z toho, co poslal klient
3. model → `tool_use` → retrieval → položky s `ref` → model → stream
4. `assistant` a `tool` řádky celého dotazu se drží v paměti a zapíšou se **jednou transakcí
   na konci**

Bod 4 je důvod, proč není potřeba sloupec `status`. Přerušený dotaz (výjimka, nebo ve
Streamlitu jakákoli interakce během streamu, která vyvolá rerun a generátor zahodí) nechá
v databázi **jen osiřelou otázku** — ne konverzaci s `tool_use` bez odpovědi. UI chybu
ukáže, další dotaz na ni nenaváže.

**Smazání konverzace.** Soft delete: `deleted_at` na `conversations`, zprávy zůstávají.
Dokumentů se **nedotýká** — in-chat přílohy přežijí, jinak by archiv neměl citace kam
odkázat. Trvalé smazání (GDPR, žádost klienta) se teď nestaví; `deleted_at` ho umožňuje
doplnit jako purge úlohu.

## In-chat soubory

Soubor přijde jedním submitem s otázkou, takže tok je pokračování zápisu dotazu:

1. INSERT `user` řádku
2. `ingest_document(data, filename=…, message_id=<ten user řádek>)`; namespace `user_files`,
   do payloadu chunků jde navíc `conversation_id`
3. teprve pak retrieval a odpověď — jinak by model o právě přiloženém souboru nevěděl

Bod 3 znamená, že dotaz s přílohou čeká na Docling parse, tedy jednotky až desítky sekund. UI
to musí ukázat jako vlastní krok („zpracovávám přílohu…"), ne jako zamrzlý spinner.

`message_id` říká UI, pod kterou zprávou soubor vykreslit, a v archivu je vidět, kde
v konverzaci vznikl. Vlastní `conversation_id` na řádku není — je to `message.conversation_id`,
jeden join. Do **payloadu chunku** se ale zapisuje, protože retrieval podle něj filtruje
a vektorová databáze joiny nemá.

Retrieval filtruje `extra_filter={"conversation_id": …}` — `query_chunks`
(`src/law_agent/retrieval/retriever.py`) ten parametr už má. Potřeba payload index na
`conversation_id`. Filtrovat na `message_id` nemá smysl: soubor přiložený ve třetí zprávě má
být dohledatelný i v desáté.

## Balíčky

- `src/law_agent/conversations/` — Pydantic doména, překlad bloků na LangChain, `ask()`
- `src/law_agent/chain/` — nástroj `search`, system prompt, vykreslení tool výsledku

## Testy

Cenné je to, co se dá udělat tiše špatně a projeví se až v archivu za měsíc. Většina se
obejde bez databáze:

- **překladová vrstva** — round-trip LangChain zpráva → bloky → LangChain zpráva pro každou
  roli a typ bloku, včetně pořadí `reasoning` před `text` a vazby `tool_use` ↔ `tool_call_id`
- **rozřešení citací** — značka mimo nabídnutou množinu se zahodí; opakovaná se započítá
  jednou; pořadí odpovídá prvnímu výskytu
- **přidělení `ref`** — druhé volání nástroje v jednom dotazu navazuje, další dotaz začíná
  od 1
- **replay** — historie pro model ztratí `tool` řádky z minulých dotazů, nechá `user`
  / `assistant` text a zahodí koncový `user` řádek bez odpovědi

S databází:

1. `unique (conversation_id, seq)` drží a zprávy se čtou v pořadí
2. soft-deleted konverzace zmizí ze seznamu, její `documents` zůstanou
3. výjimka během streamu nechá v konverzaci jen `user` řádek

## Dotčené soubory

**Nové**

- `src/law_agent/conversations/{models,blocks,service}.py`
- `src/law_agent/chain/tools.py` — nástroj `search`
- `tests/test_blocks.py`, `tests/test_conversations.py`

**Měněné**

- `src/law_agent/chain/prompt.py` — `build_messages` mizí (kontext už nejde system zprávou),
  `render_context` čísluje podle `ref` a vykresluje tool výsledek; system prompt dostane
  pravidlo pro formulaci vyhledávacího dotazu
- `src/law_agent/chain/answer.py` — dvě volání modelu s `tool_choice`, ne jedno
- `src/law_agent/chain/citations.py` — `Citation` dostává `ref` a `content`, stěhuje se do
  `conversations/models.py`; `used_indexes` nahrazuje `used_refs`; docstring odkazuje na
  zrušený spec
- `src/law_agent/ingestion/files/chunker.py` — `conversation_id` do payloadu, když je přítomný
- `tests/test_citations.py`, `tests/test_prompt.py` — následují změnu výše
- `ui/streamlit_app.py` — historie z DB místo `session_state`, volání `ask()`, výběr
  konverzace v sidebaru, krok „zpracovávám přílohu"

## Mimo rozsah

- **Agentní smyčka** — jedno kolo teď; přechod je `while` bez zásahu do schématu
- **Průběžný `streaming` řádek updatovaný po chuncích** — byl by UPDATE na každý chunk kvůli
  resume, který nikdo nemá
- **Trvalé mazání konverzací** — `deleted_at` ho umožňuje doplnit jako purge úlohu
- **Ořezávání `text` v tool výsledcích** — pár desítek konverzací se do databáze vejde. Až se
  to změní, je to úloha nad jsonb, ne změna schématu: `text` je v `content` oddělený od
  citačních klíčů, takže ořezání proklik neutrhne.
- **Generování názvu konverzace modelem**
- **Logování a audit trail** — až s agent loopem (Langfuse self-hosted) a s auth

## Ověření

- `uv run streamlit run ui/streamlit_app.py` — položit dotaz, **obnovit stránku**, historie
  i citace jsou tam; „Nová konverzace" založí druhou a obě jsou v sidebaru
- ruční kontrola: `SELECT seq, role FROM messages WHERE conversation_id = ? ORDER BY seq`
  vrátí za jeden dotaz čtyři řádky `user` / `assistant` / `tool` / `assistant`
- ruční kontrola: `blocks` druhého řádku obsahuje `tool_use` s `query`, které si napsal
  model, a to query obsahuje termíny z otázky
- vypnout OpenRouter klíč a položit dotaz — v konverzaci zůstane jen `user` řádek, UI chybu
  ukáže a další dotaz na ni nenaváže
- kliknout během streamu — totéž: `user` řádek bez odpovědi, po refreshi konverzace bez
  rozbitého tvaru
- druhý dotaz ve stejné konverzaci — v promptu se objeví text prvního kola, ale ne jeho
  chunky; refy začínají znovu od 1
- smazat konverzaci — zmizí ze seznamu, `SELECT` s `deleted_at IS NOT NULL` ji najde,
  její `documents` řádky existují dál
- přiložit soubor ke zprávě — `documents.message_id` ukazuje na ten `user` řádek, chunky mají
  v payloadu `conversation_id`; po refreshi je soubor vidět pod toutéž zprávou
