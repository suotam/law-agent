# RAG chain a testovací UI

_Spec, 2026-08-05._

## Kontext

Ingest, chunking, indexace a hybridní retrieval fungují. Chybí poslední krok: z nalezených
chunků udělat **odpověď**. Dnes jde retrieval otestovat jen přes `scripts/query_laws.py`
a `scripts/query_files.py`, které vypíšou chunky — což odpoví na otázku „našlo se to?", ale
ne na otázku „dá se z toho odpovědět?".

Spec perzistentní vrstvy (`2026-08-05-persistence-layer-design.md`) tenhle krok explicitně
předřazuje sám sobě: databáze má smysl až ve chvíli, kdy je co archivovat, a tvar citací se
musí ustálit dřív, než se začne zapisovat.

Cíl tohohle kroku je proto **měřicí přístroj**, ne produkt. Chain má být co nejjednodušší,
aby při špatné odpovědi šlo rozlišit chybu retrievalu od chyby promptu. Vše, co do měření
vnáší proměnnou navíc — agent smyčka, routing, přeformulování dotazu — je odloženo.

## Rozhodnutí

| Otázka | Volba | Proč |
|---|---|---|
| Tvar chainu | **Lineární pipeline**, ne agent | Agent přidává proměnné (hledal? čím? kolikrát?) právě tam, kde se měří kvalita retrievalu. Přechod na agenta je aditivní — viz „Cesta k agentovi" |
| Framework | **Jen `langchain-core`** | Zprávy, chat model a streaming jsou protokol, který se vyplatí přebrat. LCEL ani LangGraph nemá lineární chain co nabídnout |
| Vektorová abstrakce | **Žádná** | `query_chunks` dělá jedno Qdrant volání s dvěma prefetch větvemi a RRF fúzí; `VectorStore` by tuhle kontrolu vzal bez protihodnoty |
| Rozsah hledání | **Oba namespace v jednom volání**, `MatchAny` | Dvě volání a sloučení podle skóre nedává smysl — RRF skóre ze dvou oddělených fúzí nejsou porovnatelná |
| Výběr zdrojů | **Ruční přepínač v sidebaru**, oba předvybrané | LLM router má tvrdý failure mode (špatná větev = správný chunk nedosažitelný); navíc řeší problém, který zatím nikdo nepozoroval. Přepínač je zároveň experiment, který data pro router vyrobí |
| Kontextualizace dotazu | **Nedělat** | Retrieval jede nad poslední user zprávou. Až to začne selhávat, bude vidět na kterých dotazech |
| Historie | **V promptu ano, v retrievalu ne** | Model potřebuje vědět, o čem je řeč; retrieval potřebuje jeden konkrétní dotaz |
| Chunky z minulých kol | **Neposílat** | Značka `[n]` je pozice v seznamu; se třemi koly by `[1]` znamenala pokaždé něco jiného. Informace přežívá ve starých odpovědích |
| Umístění UI | **`ui/` mimo `src/`** | `src/law_agent/` je knihovna, kterou bude importovat budoucí API. Streamlit je konzument, stejná role jako `scripts/` |
| Perzistence | **Žádná** | Historie žije v `st.session_state`. Postgres je další krok, ne tenhle |

## Architektura

### Balíčky

```
src/law_agent/retrieval/search.py    search() nad víc namespace — tool-shaped
src/law_agent/chain/citations.py     Citation, from_chunk(), parsování značek
src/law_agent/chain/prompt.py        systémový prompt + kontextový blok
src/law_agent/chain/answer.py        stream_answer()
ui/streamlit_app.py                  Streamlit
```

**V `chain/` ani v `retrieval/` není jediné `st.`.** Chain dostane zprávy, vrátí tokeny.
Budoucí FastAPI endpoint je druhý konzument, ne přepis.

`search` patří do `retrieval/`, ne do `chain/`, protože je to retrieval — `chain/` skládá
prompt a mluví s modelem.

### Kontrakt

```python
def search(
    query: str,
    *,
    scope: Sequence[str] = (LAWS_NAMESPACE, FILES_NAMESPACE),
    limit: int = 10,
) -> list[RetrievedChunk]

def stream_answer(
    messages: Sequence[BaseMessage],
    chunks: Sequence[RetrievedChunk],
) -> Iterator[str]
```

Dvě funkce, ne jedna, ze tří důvodů:

1. **UI potřebuje chunky dřív než první token** — debug panel se vykreslí, zatímco odpověď
   teprve teče.
2. **Testovatelnost** — `search` se testuje bez LLM, `stream_answer` proti fake modelu.
3. **Pevné pořadí „nejdřív retrieval, pak model" není ani v jedné z nich.** Žije u volajícího,
   tedy v UI — v části, která se s Streamlitem stejně zahodí.

`search` je psaná **tool-shaped už teď**: ploché serializovatelné argumenty a docstring, který
se jednou stane popisem nástroje pro model.

Citace se nevrací zvlášť. Jsou odvozené z `chunks` 1:1 podle pořadí — značka `[n]` **je**
index v seznamu, takže druhá kolekce by držela stejnou informaci dvakrát.

### Citace

`Citation` má přesně tvar ze specu perzistence, aby se dal jednou zapsat beze změny:

```python
{
    "kind": "document",
    "label": "smlouva.pdf, s. 4 – Odstoupení",
    "doc_id": "…",
    "pages": [4],
    "chunk_id": "…",
}
{"kind": "law", "label": "§ 1829 obč. zák.", "law_id": "…", "anchor": "…", "chunk_id": "…"}
```

`Citation.from_chunk` odvozuje z payloadu, který už dnes existuje:

| pole | `laws` | `org_files` |
|---|---|---|
| `kind` | `"law"` | `"document"` |
| `label` | `citation` | `citation` |
| klíč zdroje | `law_id` | `doc_id` |
| lokátor | `anchor_fragment_id` → `anchor` | `pages` |

Neznámý namespace je chyba, ne tichý fallback — nový zdroj musí své mapování dodat vědomě.

Model dostane všech `limit` chunků, ale cituje jen některé. Po dostreamování se z textu
vytáhnou použité značky regexem a zobrazí se **jen citované** položky. Značka mimo rozsah
(model si vymyslí `[12]` z deseti chunků) se zahodí — nesmí shodit render.

### Skládání promptu

Vstup pro model se skládá znovu každý tah:

```
SystemMessage(systémový prompt + kontextový blok pro TENHLE dotaz)
*historie (končí aktuální HumanMessage)
```

Jeden systémový message; historie zůstává čistá — jen `user` / `assistant` text, bez
zapečeného kontextu. Kdyby se kontext zapekl do uložené user zprávy, u čtvrtého dotazu by
model dostal chunky ze všech tří kol, značky by kolidovaly a přepis určený jednou pro
Postgres by obsahoval něco, co uživatel nikdy nenapsal.

Kontextový blok renderuje každý chunk jako `[n] {citation}` a pod tím text.

Systémový prompt je v češtině a má tři pravidla:

1. Odpovídej **jen** z dodaného kontextu.
2. Každé tvrzení označ `[n]`.
3. Když kontext odpověď neobsahuje, **řekni to** místo dohadování.

### Změna v retrieveru

`query_chunks` (`src/law_agent/retrieval/retriever.py`) dostane
`namespace: str | Sequence[str]`. `_build_filter` použije `MatchValue` pro string,
`MatchAny` pro sekvenci. Stávající volající (`scripts/query_laws.py`,
`scripts/query_files.py`) se nemění.

`ingestion/laws/models.py` dostane `NAMESPACE = "laws"` jako konstantu, zrcadlově
k `ingestion/files/models.py:18`. Dnes je `"laws"` jen výchozí hodnota argumentu
`to_payload`, takže by se řetězec musel psát ručně na dalších dvou místech.

### Streamlit

**Sidebar:** multiselect zdrojů (Zákony / Dokumenty, oba předvybrané), slider na počet
chunků, jméno modelu z `settings`.

**Hlavní plocha:** `st.chat_message` historie, `st.chat_input`. U každé odpovědi asistenta:

- streamovaný text
- **citované zdroje** — `st.expander` s labelem, uvnitř celý text chunku
- `st.expander("Nalezené chunky (N)")` — všechny, se skóre, namespace a labelem; citované
  zvýrazněné

Debug panel není kosmetika. Je to důvod, proč tenhle krok existuje: když je odpověď špatná,
ukáže, jestli správný chunk vůbec vytažený byl (→ problém promptu) nebo nebyl (→ problém
retrievalu). Zároveň ukáže, jestli sdružené hledání jeden namespace nevyhladovělo.

Stav v `st.session_state.messages`:

```python
{"role": "user", "text": "…"}
{"role": "assistant", "text": "…", "chunks": [...]}
```

`chunks` slouží **jen zobrazení** — po rerunu musí debug panel u staré zprávy pořád fungovat.
Do modelu nikdy nejdou.

## Cesta k agentovi

Roadmapa počítá s agentem, routingem a dalšími nástroji. Co z tohohle MVP přežije:

| dnes | v agentovi |
|---|---|
| `search()` | **tělo nástroje** — obalí se dekorátorem, jinak beze změny |
| `stream_answer()` | **krok smyčky** — mění se skládání kontextu, ne volání modelu |
| `Citation` | beze změny — tvar je z persistence specu |
| pevné pořadí retrieval → model | **zahodí se**, ~10 řádků v `ui/streamlit_app.py` |

Až kontext přijde jako `ToolMessage` s vlastním `tool_call_id`, vyřeší se tím i identita
podkladů napříč koly, kterou dnešní číslování podle pozice v seznamu neumí.

## Co se záměrně nedělá

- **Query translation / kontextualizace** — až ji vyžádá pozorované selhání
- **LLM router nad namespace** — ruční přepínač vyrobí data, na kterých se router dá postavit
- **LangGraph, LCEL** — lineární chain z nich nic nemá
- **Perzistence, upload z UI, auth** — vlastní specy
- **Reranking, komprese kontextu** — bez naměřeného problému spekulace

## Dotčené soubory

**Nové**

- `src/law_agent/retrieval/search.py`
- `src/law_agent/chain/{__init__,citations,prompt,answer}.py`
- `ui/streamlit_app.py`
- `tests/{test_search,test_citations,test_answer}.py`

**Měněné**

- `src/law_agent/retrieval/retriever.py` — `namespace: str | Sequence[str]`, `MatchAny`
- `src/law_agent/retrieval/__init__.py` — export `search`
- `src/law_agent/ingestion/laws/models.py` — konstanta `NAMESPACE`
- `src/law_agent/ingestion/laws/__init__.py` — export `NAMESPACE`
- `tests/test_retriever.py` — větev `MatchAny`
- `pyproject.toml` — `streamlit` přes `uv add`

## Pořadí implementace

1. `MatchAny` v `query_chunks` + konstanta `NAMESPACE` pro zákony
2. `search()` nad víc namespace
3. `Citation` + parsování značek
4. Prompt a `stream_answer()`
5. Streamlit

Kroky 1–4 jsou hotové a otestované dřív, než se sáhne na UI.

## Ověření

- `uv run pytest` — projde
  - `search` vrací chunky z obou namespace v jednom pořadí; omezený `scope` vrátí jen svůj
  - `Citation.from_chunk` mapuje oba namespace; neznámý namespace vyhodí
  - parsování značek: `[1][2]`, opakovaná značka, značka mimo rozsah
  - `stream_answer` proti fake chat modelu: kontext je v system message, historie navazuje,
    uložený přepis zůstal bez kontextu
- `uv run ruff check` a `uv run pyright` — čisté
- `uv run streamlit run ui/streamlit_app.py` — aplikace naběhne
- dotaz, který patří **jen do zákonů** — odpověď cituje `§`, debug panel ukazuje `laws`
- dotaz, který patří **jen do dokumentů** — odpověď cituje soubor a stránku
- dotaz, který patří **do obou** — v desítce jsou oba namespace; pokud ne, je to signál pro
  kvótu, ne chyba implementace
- dotaz **mimo indexovaná data** — model řekne, že odpověď v podkladech není, a nevymyslí si ji
- dvě otázky za sebou, kde druhá odkazuje na první — model naváže; debug panel u druhé ukazuje
  chunky nalezené jen k druhému dotazu
- přepnutí sidebaru na jeden zdroj — debug panel obsahuje jen ten namespace
