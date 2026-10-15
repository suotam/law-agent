# Ingestce obecných souborů

Pipeline pro dokumenty, které nejsou zákony (PDF, DOCX, …): parsování přes
docling-serve s českým Tesseract OCR, chunkování Doclingovým `HybridChunker`em,
uložení do DB + blob store a indexace do namespace `org_files`.

Návrhové zdůvodnění je v
[specu](superpowers/specs/2026-08-04-docling-ingestion-design.md); tenhle
dokument je provozní.

## Tok

```
soubor (PDF/DOCX/…)
   │  POST /v1/convert/file
   ▼
docling-serve (kontejner)      bajty → DoclingDocument, nic víc
   │  json_content
   ▼
ingest_document()              DB (Folder/Document) + blob store + chunking
   │  ChunkLike
   ▼
Qdrant, namespace "org_files"
```

docling-serve o RAG, chunkách ani Qdrantu neví — je to čistý parser, a proto
vyměnitelný.

## Předpoklady

```bash
docker compose up -d          # Qdrant + docling-serve
```

V `.env` stačí `DOCLING_URL` (default `http://localhost:5001`), plus proměnné
pro Qdrant, DB a embedding API, které už používá ingestce zákonů.

## Použití

```bash
# parse + chunk, bez DB a bez embedding API — na ladění chunkingu
uv run scripts/ingest_files.py data/files/*.pdf --dry-run --stats

# čitelný výpis chunků do data/file_chunks/ — na kontrolu OCR a hranic chunků
uv run scripts/ingest_files.py data/files/smlouva.pdf --folder Vzory --dump

# ostrý běh: uloží do DB, chunkuje, indexuje do org_files a uklidí sirotky
uv run scripts/ingest_files.py data/files/*.pdf --folder Vzory/Smlouvy
```

Užitečné přepínače: `--max-tokens` (rozpočet chunku, default 768), `--folder`
(cesta ve složkové struktuře; povinná mimo `--dry-run`, chybějící složky se
vytvoří), `--name` (uložené jméno, dává smysl jen pro jeden soubor),
`--no-cache`.

## Identita dokumentu a re-ingestce

`doc_id` je UUID řádku v tabulce `documents`, ne cesta na disku. Chunky jej
nesou v payloadu a jejich `point_id` je z něj odvozený, takže re-indexace
téhož `document_id` přepíše chunky v místě; protože nová verze může mít méně
chunků než stará, skript po indexaci volá `prune_orphans` a smaže zbylé body.

Duplicity se řeší podle obsahu, ne jména: DB má unique index na
(`folder_id`, `blob_sha256`). Nahrání stejného souboru do stejné složky skončí
`DuplicateDocumentError` — skript to odchytí, přeskočí a embedding API se
nevolá. Stejný soubor v jiné složce nebo pod jiným jménem je nový dokument.

## OCR

Klient posílá `ocr_preset=tesseract` a `ocr_lang=["ces","eng"]`. Explicitní
preset je nutný: default `auto` vybere rapidocr, který český model nemá.

Režim je `do_ocr=true, force_ocr=false` — OCR jede jen na bitmapové oblasti,
takže digitálně vytvořená PDF používají svou přesnou textovou vrstvu a přes
Tesseract jdou jen skeny.

**Sken je řádově pomalejší.** Orientačně na M1 CPU: skenovaná jednostránková
smlouva ~8 s, devítistránkové digitální PDF ~26 s.

**Známé omezení kvality:** na skenech Tesseract čte `§` jako `S` a `IČO` jako
`ICO`. Vyhledávání podle paragrafu nad skenovanými dokumenty proto není
spolehlivé; u digitálních PDF se to neděje, tam se OCR vůbec nepoužije.

Vizuální kontrola parsovaného výstupu: Gradio UI na <http://localhost:5001/ui>.

## Cache parsovaných dokumentů

Parsované dokumenty se ukládají do `data/parsed/<stem>.docling.json`. OCR je
zdaleka nejdražší krok, takže díky cache stojí přechunkování s jiným
`--max-tokens` zlomek sekundy místo desítek sekund.

Cache zahoď (`rm -rf data/parsed`), když:

- se změní verze docling-serve nebo OCR nastavení — jinak bys ladil na starém
  výstupu,
- se změní obsah souboru pod stejným jménem (cache se klíčuje jménem, ne hashem).
