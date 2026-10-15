# Source-agnostic chunk kontrakt — design

_Verze: v1, přijato 2026-08-04._

## Cíl

Připravit `indexing/` a `retrieval/` na druhý typ zdroje (`org_files`,
`user_files` — viz [[project-spec]], MVP roadmapa body 3 a 5), aniž by se
přidávalo cokoli z document processingu. Po této změně má přidání generických
souborů znamenat **jen přidat nový modul** (loader + chunker + `FileChunk`),
bez zásahu do indexovací a retrievalové vrstvy.

Sám document processing (Docling, `FileChunk`, upload flow) je **mimo rozsah**
tohoto designu.

## Výchozí stav

`indexing/` a `retrieval/` jsou už dnes namespace-agnostické — pracují nad
libovolným namespace jako payload filtrem (viz
[hybrid-retrieval design](2026-08-04-hybrid-retrieval-design.md)). Co
agnostické není:

1. `indexer.py` importuje konkrétní model `from law_agent.ingestion.models
   import Chunk`, i když z něj používá jen `point_id`, `content_hash`, `text`
   a `to_payload(namespace=...)`.
2. `RetrievedChunk` (v `retrieval/retriever.py`) má natvrdo pole
   `law_citation`, které u generického souboru neexistuje.
3. Jméno `Chunk` implikuje jediný chunk model; jakmile vznikne druhý, je
   matoucí.
4. Payload kontrakt (které klíče musí každý zdroj dodat, aby indexer
   a retriever fungovaly) není nikde zapsaný.

## Návrh

### 1. `ChunkLike` Protocol, definovaný konzumentem

Nový modul `src/law_agent/indexing/protocols.py` s `Protocol`, který popisuje
minimum, jež indexer od chunku potřebuje:

```python
class ChunkLike(Protocol):
    point_id: str
    content_hash: str
    text: str

    def to_payload(self, *, namespace: str) -> dict[str, Any]: ...
```

Protocol žije v `indexing/`, ne v `ingestion/`, protože **rozhraní vlastní
konzument**. Producenti (dnešní `LawChunk`, budoucí `FileChunk`) ho splňují
strukturálně, bez dědění a bez importu. Vedlejším efektem je, že `indexing`
přestane na `ingestion` záviset úplně.

Protocol není `@runtime_checkable` a nikde se nedělá `isinstance` — je to
čistě typová věc pro pyright, bez runtime dopadu.

### 2. Payload kontrakt jako docstring

Dnes existuje implicitní dohoda o klíčích v payloadu, roztroušená mezi dvě
vrstvy. Zapíše se jako docstring k `ChunkLike.to_payload` — jediné místo,
kam se budoucí `FileChunk` podívá, aby věděl, co musí splnit:

| Klíč | Čte | K čemu |
|---|---|---|
| `namespace` | `indexer._fetch_existing`, `retriever._build_filter` | skip-check, filtrace dotazu |
| `content_hash` | `indexer._fetch_existing` | přeskočení nezměněných chunků |
| `chunk_id` | `retriever._to_retrieved_chunk` | identita výsledku |
| `citation` | `retriever._to_retrieved_chunk` | citace zdroje v odpovědi |
| `text` | `retriever._to_retrieved_chunk` | tělo výsledku |

Cokoli nad rámec těchto pěti klíčů je specifické pro daný zdroj a doputuje
k volajícímu přes `RetrievedChunk.payload`.

### 3. `Chunk` → `LawChunk`

Čisté přejmenování třídy v `ingestion/models.py`, bez jakékoli změny polí
nebo chování. Dotčená místa: `models.py`, `chunker.py`, `validation.py`,
`ingestion/__init__.py` (import i `__all__`), `tests/factories.py`.

Zpětně kompatibilní alias `Chunk` se **nezavádí** — projekt nemá externí
konzumenty a alias by jen prodloužil dobu, kdy v kódu žijí dvě jména pro
jednu věc.

### 4. `RetrievedChunk` bez law-specific pole

Pole `law_citation: str | None` se z `RetrievedChunk` odstraní. Zbylá pole
(`score`, `chunk_id`, `citation`, `text`, `payload`) dávají smysl pro každý
zdroj.

Hodnota nezmizí — payload ji nese dál, takže `scripts/query_laws.py` ji čte
jako `result.payload.get("law_citation")`. Jde o jedinou změnu v tomto
designu, která se dotkne běžícího kódu.

## Dopad na kvalitu retrievalu zákonů: žádný

Ověřeno, že jméno třídy neovlivňuje nic z řetězce, který určuje kvalitu:

| Článek řetězce | Kde vzniká | Závisí na jménu třídy |
|---|---|---|
| dělení textu na chunky | `LawChunker._plan_node` / `_render` | ne |
| embedovaný text | `chunk.text` (header + body) | ne |
| `chunk_id` | `_chunk_id()`: `law_id\|part\|anchor\|first\|last\|index` | ne |
| `point_id` | `uuid5(_POINT_ID_NAMESPACE, chunk_id)` | ne |
| `content_hash` | `sha256(text)` | ne |
| payload | `to_payload()` — ručně psaný dict | ne |
| dense + sparse vektor | oba z `chunk.text` | ne |
| ranking | `query_points` + RRF fúze | ne |

V kódu se nikde nepoužívá `model_dump()`, `pickle`, `__class__` ani
`type().__name__` — veškerá serializace je ručně psaná s explicitními klíči,
takže jméno třídy nikam neuniká.

**Praktický důsledek:** po změně se nespustí žádné přeembedování.
`content_hash` zůstane stejný, takže `indexer.py` všechny existující chunky
přeskočí. Data v Qdrantu zůstávají platná; žádné náklady na embedding API.

## Testování

### Nové testy — jádro této změny

`test_indexer.py` a `test_retriever.py` dostanou minimální fake chunk třídu,
která splňuje `ChunkLike` a o zákonech neví nic:

```python
@dataclass
class _FakeChunk:
    point_id: str
    content_hash: str
    text: str

    def to_payload(self, *, namespace: str) -> dict[str, Any]: ...
```

Ověří se, že indexace i hybridní retrieval fungují nad zdrojem bez jediného
law-specific pole, pod namespace `org_files`. Bez tohoto testu by byl Protocol
jen kosmetika — tohle je jediná záruka, že refaktor splnil svůj účel.

### Regresní ověření, že se pro zákony nic nezměnilo

Nejtvrdší důkaz je bit-identický payload před a po změně:

```bash
uv run scripts/chunk_laws.py data/laws/*.json --out /tmp/chunks-before   # před
uv run scripts/chunk_laws.py data/laws/*.json --out /tmp/chunks-after    # po
diff -r /tmp/chunks-before /tmp/chunks-after                             # musí být prázdný
```

Vedle toho `uv run pytest` (baseline před změnou, porovnat po ní) a
`uv run pyright`, který odhalí zapomenuté rename sites — hlavní mechanické
riziko této změny.

`tests/test_real_laws.py` běží nad skutečnými zákony z `data/laws/`
a kontroluje citace i pokrytí textu, takže případná regrese se projeví na
reálných datech, ne jen na fixturách.

## Nové závislosti

Žádné.

## Mimo rozsah

- Docling a parsování PDF/DOCX.
- Model `FileChunk` a jeho `chunk_id` strategie.
- Upload endpoint, `session_id` a TTL pro `user_files`.
- Role-based filtrace nad `org_files` (project-spec, otevřené rozhodnutí).
- Jakákoli změna Qdrant schématu nebo klíčů v payloadu — ta by si vynutila
  reindexaci, což tento design explicitně nedělá.
