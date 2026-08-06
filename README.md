# Local RAG for a Personal Knowledge Base
![CI](https://github.com/thanutgit/<ชื่อ-repo>/actions/workflows/ci.yml/badge.svg)

A question-answering system over your own documents. Reads Markdown, PDF, Word, Excel, and CSV. Everything runs locally — nothing is sent to an external API.

Ask in natural language. The system decides whether the question calls for semantic search over your notes or an actual calculation over your spreadsheets, and answers from what it finds.

> **Status:** Working end to end — web UI, REST API, CLI, 91 tests, CI, and a container build. Not deployed and has no authentication yet, so it's localhost-only for now. See [Known limitations](#known-limitations).

---

## Why

Obsidian's search is keyword-based: if you don't remember the exact words you wrote, you won't find the note. This searches by meaning instead.

The second constraint was privacy. Uploading personal notes to a hosted model wasn't an option, so every component — embedding model, LLM, and both databases — runs on the machine.

---

## Architecture

```
Documents (.md .pdf .docx .xlsx .csv)        Browser UI
        │                                        │
        ▼                                        ▼
┌────────────────────────────────────────────────────────┐
│  FastAPI   /ingest  /query  /tables  /export  /health  │
└───┬─────────────────────┬──────────────────┬───────────┘
    │                     │                  │
    ▼                     ▼                  ▼
┌─────────┐      ┌──────────────────┐   ┌──────────────────┐
│ Qdrant  │      │   PostgreSQL     │   │      Ollama      │
│ vectors │      │ sync state,      │   │ bge-m3 (embed)   │
│         │      │ chat history,    │   │ qwen3:8b  (LLM)  │
│         │      │ tabular data     │   │                  │
└─────────┘      └──────────────────┘   └──────────────────┘
   :6333               :5432                  :11434
```

Qdrant and PostgreSQL run in Docker. Ollama runs on the host so it can reach the GPU directly.

---

## Two paths for two kinds of question

Vector search retrieves a handful of passages. That works for *"how do I fix INC-001"* and fails for *"how many servers are in production"* — the model can only count what it was shown, and it was shown five chunks out of forty-nine.

Measured on a 20-question test set, retrieval-only answered 6/6 lookup questions correctly and 1/7 aggregation questions. Asked how many production servers existed, it answered 23. The real number was 76.

So spreadsheets and CSVs are also loaded into PostgreSQL as real tables. A router classifies each incoming question, and counting questions become SQL that runs over the full dataset:

```sql
SELECT COUNT(*) FROM "data_server_inventory" WHERE "environment" = 'production'
```

The UI labels which path produced each answer, and the generated SQL is one click away.

---

## Tech stack

| Layer | Choice | Why |
|:---|:---|:---|
| Vector store | Qdrant | Payload filtering and indexing, plus a dashboard that made debugging retrieval much easier |
| Relational DB | PostgreSQL | Per-file sync state, chat history, and the tabular data that SQL queries run against |
| Embeddings | `bge-m3` via Ollama | Multilingual — the vault mixes Thai and English. 1024-dim vectors |
| LLM | `qwen3:8b` via Ollama | Handles Thai well and fits in available VRAM |
| API | FastAPI | Pydantic validation and generated OpenAPI docs |
| Frontend | Vanilla HTML/CSS/JS | One file served by FastAPI itself — no build step, no CORS config, and the UI stays inspectable |
| File readers | pdfplumber, python-docx, openpyxl | Each converts its format to Markdown; everything downstream is format-agnostic |
| OCR (optional) | Tesseract | Only invoked for PDF pages with no text layer |

---

## Quick start

**Prerequisites:** Docker, Python 3.12+, and [Ollama](https://ollama.com) running.

```bash
# 1. Pull the models
ollama pull bge-m3
ollama pull qwen3:8b

# 2. Configure
git clone <this-repo> && cd obsidian-rag
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD and OBSIDIAN_VAULT_PATH

# 3. Start the databases
docker compose up -d

# 4. Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional — only needed to read scanned PDFs
sudo apt install tesseract-ocr tesseract-ocr-tha poppler-utils

# 5. Index your documents
python scripts/02_ingest.py

# 6. Start the app
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** for the web UI, or **/docs** for the API reference. A terminal client is also available: `python scripts/03_query.py`

To run everything in containers instead, see [DEPLOYMENT.md](DEPLOYMENT.md).

---

## API

| Endpoint | Method | Purpose |
|:---|:---|:---|
| `/` | GET | Web UI |
| `/health` | GET | Service status and current chunk count |
| `/ingest` | POST | Sync documents into the vector store and SQL tables |
| `/query` | POST | Ask a question; returns an answer with sources or a result table |
| `/tables` | GET | Tables loaded for SQL querying |
| `/export/xlsx` | POST | Download a result table as Excel |

**Example**

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What did I write about panang curry?"}'
```

```json
{
  "answer": "...",
  "mode": "search",
  "sources": [
    {
      "file_path": "recipes.md",
      "heading": "Favourite dishes > Panang curry",
      "chunk_index": 0,
      "score": 0.6714,
      "text_preview": "..."
    }
  ],
  "latency_ms": 4300,
  "session_id": "3f2b..."
}
```

Counting questions return `"mode": "sql"` with the query that ran and the full result table instead of `sources`.

Every answer carries what it was based on, so claims can be traced back to a specific section of a specific file.

---

## How it works

### Supported formats

| Format | Handling |
|:---|:---|
| `.md` `.txt` | Read directly, with encoding fallback for older Thai files (cp874, tis-620) |
| `.pdf` | Text extracted by character coordinate, so letter-spaced designs stay intact. Pages with no text layer fall back to OCR |
| `.docx` | Word heading styles map to Markdown headings; tables become Markdown tables |
| `.xlsx` `.xlsm` | Each sheet becomes a section, and multiple tables within one sheet are detected separately. Formulas are read as their computed values |
| `.csv` `.tsv` | Delimiter detected automatically; the column header repeats in every block so a row is never separated from its labels |

Adding a format means writing one reader that returns Markdown and registering it. Nothing downstream changes.

### Ingestion

1. Recursively scan for any supported file type
2. Convert to Markdown via that format's reader
3. Split along Markdown headings, so each chunk is a complete section rather than an arbitrary slice. Sections over the limit fall back to splitting by paragraph, then sentence. Every chunk carries its heading path, which preserves context and gives the embedding something to anchor on
4. Normalize Unicode — in Thai, `เ`+`เ` and `แ` render identically but embed differently
5. Embed with `bge-m3` and upsert into Qdrant
6. Spreadsheets and CSVs are additionally loaded into PostgreSQL as typed tables, with a catalog recording each column's type and its distinct values

**Incremental sync.** A SHA-256 hash of each file's raw bytes is stored in PostgreSQL — bytes rather than extracted text, so a file can be skipped before the expensive conversion runs at all, which matters when that conversion is OCR. On subsequent runs:

- unchanged files are skipped without invoking the embedding model
- modified files have their old chunks deleted before re-indexing, preventing stale chunks from lingering when a file gets shorter
- deleted files are removed from Qdrant, PostgreSQL, and their SQL tables

Chunk IDs derive deterministically from `(file_path, chunk_index)` via UUIDv5, so re-running overwrites rather than duplicates.

### Retrieval

1. If the conversation has history and the question can't stand alone, rewrite it to be self-contained — *"what about staging?"* becomes *"how many servers are in staging"*. The rewrite is discarded if it drops a keyword the user actually typed
2. Route: does this need a calculation over a full table, or a search over passages?
3. **Search path** — embed with the same model used at index time, retrieve nearest chunks by cosine similarity, discard anything below a score threshold so weakly related passages don't pad the context, then generate under a system prompt that restricts the model to the supplied context and instructs it to say so when the documents don't contain an answer
4. **SQL path** — generate a query against the catalog schema, run it through five checks, execute read-only with a timeout, and hand the model a summary rather than the full result

### Guarding generated SQL

The model writes SQL that actually executes, so every query passes five checks first:

| Step | What it does |
|:---|:---|
| Clean | Strip markdown fences and commentary |
| Repair | Fix known mistakes — `COUNT(*) OVER ()` combined with `GROUP BY` counts groups, not members |
| Filter | Remove `WHERE` clauses using values the question never mentioned |
| Validate | `SELECT` only, single statement, no system tables |
| Verify | Every referenced table must exist in the catalog |

Steps 2 and 3 repair; steps 4 and 5 reject and fall back to vector search. Execution is read-only with a five-second statement timeout.

The model is also handed only eight sample rows plus the true row count, never the full result — it doesn't need to see every row to write one paragraph, and given a truncated list it will count the rows it can see. The complete table goes to the browser separately.

---

## Project structure

```
readers/           One module per file format, each returning Markdown
  registry.py        Extension to reader mapping
  base.py            Shared Document type and helpers
services/          Core logic, independent of any interface
  config.py          Environment configuration, loaded once
  ollama_service.py  Embedding and chat completion
  qdrant_service.py  Vector store operations
  postgres_service.py Sync state and chat history
  tabular_service.py Loads spreadsheets into SQL tables
  sql_service.py     Query generation, validation, execution
  ingest_service.py  Ingestion pipeline
  query_service.py   Routing and retrieval
app/main.py        FastAPI routes, and serves the frontend
frontend/index.html Web UI (single file, no build step)
scripts/           CLI wrappers around the same services
tests/             91 fast tests, 9 requiring a live model
utils/
  chunking.py        Structure-aware splitting
  text_normalize.py  Unicode normalization before embedding
db/init/           Schema, applied on first container start
```

The CLI and the API call the same service functions, so there is one implementation of each pipeline rather than two that can drift apart.

---

## Tests

```bash
pytest -m "not llm"    # 91 tests, ~2s, no dependencies
pytest                 # adds 9 end-to-end tests, ~3min, needs Ollama and data
```

Split in two because a suite that takes four minutes stops being run. The fast tier covers what can be checked without a model — SQL validation and repair, file readers, chunking, Unicode normalization, rewrite safety. The slow tier asks real questions with known answers.

Nearly every test corresponds to a bug that actually happened. LLM output isn't deterministic and prompt changes have non-local effects: a rule added to fix one case taught the model to apply it where it didn't belong, and the resulting wrong number looked entirely plausible. `tests/HOWTO_ADD_TEST.md` documents the workflow.

---

## Design decisions

**Every format converts to Markdown before anything else touches it.** The chunking, embedding, and storage steps never learn what a PDF is. Supporting a new format is one reader and one registry line, and the choice pairs well with heading-based chunking: Word heading styles, PDF section titles, and spreadsheet sheet names all become headings the splitter already understands.

**pdfplumber over pypdf.** A résumé exported from a design tool came back from pypdf as `Main tained and optimiz ed s yst em`, because the tool's letter-spacing became literal spaces. About 200 lines went into repairing those words against a dictionary before it became clear the file itself was fine — pdfplumber groups characters by coordinate and read it correctly with no repair at all, and ordered a two-column layout correctly besides. The repair code was deleted.

**Two databases and a routing layer instead of one retrieval strategy.** More moving parts than a standard RAG setup, justified by measurement rather than preference: aggregation questions were answering wrong six times out of seven, and no amount of prompt tuning fixes a model that can only see a tenth of the data.

**Chunking written by hand rather than using a framework.** LangChain and LlamaIndex both do this better. Writing it directly made the retrieval behaviour easier to reason about when results looked wrong, which happened often enough to justify it.

**Local models over a hosted API.** Privacy was the driving constraint. The cost is answer quality and latency — 3 to 8 seconds on a development machine where a hosted API would take one. `ollama_service.py` is isolated specifically so this can be swapped without touching the rest of the pipeline.

**Reasoning mode disabled.** Qwen3 generates reasoning tokens by default. For questions answered from supplied context that's latency without benefit — turning it off cut response time roughly in half.

---

## Known limitations

- **No authentication.** The API is unprotected and intended for localhost use only. See [DEPLOYMENT.md](DEPLOYMENT.md) for what would need to exist before exposing it.
- **Sensitive to spelling, unevenly.** Semantic search matches meaning, so a typo landing near the intended word still works while one landing near a different word doesn't: `buget tacker` finds the budget spreadsheet, `bugget tacker` returns nothing. Unicode normalization handles one common Thai case, but genuine misspellings still miss. Hybrid search combining BM25 with vector search is the intended fix.
- **The relevance threshold is a guess.** The current fixed cutoff came from eyeballing the score gap on a handful of queries. A threshold relative to the top score would generalize better, but tuning either properly needs a larger evaluation set.
- **Aggregation only works over tabular files.** SQL handles spreadsheets. Questions needing every chunk of a Markdown file — *"summarize everything I wrote about Docker"* — still see only what retrieval returned.
- **Negative questions are unreliable.** *"Which servers haven't been upgraded?"* is answered from retrieved passages, which may not include the answer, and the response won't indicate that.
- **OCR reads print, not handwriting.** Scans and screenshots work. Handwritten notes don't, Thai handwriting especially — Tesseract emits plausible-looking garbage rather than failing, so pages whose OCR output looks like noise are dropped instead of indexed.
- **Images inside documents aren't read.** A Word file whose instructions live in screenshots yields only its surrounding prose. Charts in spreadsheets are noted but not interpreted.
- **Spreadsheet formulas need a cached value.** Files generated programmatically and never opened in Excel have no cached results, so formulas are read as their own text.
- **The evaluation set is small.** Twenty questions over a dozen files. Enough to catch the aggregation failure, not enough to tune thresholds against.

---

## Roadmap

- API key authentication and rate limiting
- Hybrid search (BM25 alongside vector search) for typos and exact identifiers
- A larger evaluation set, used to tune the relevance threshold
- Whole-document retrieval when a question is about one specific file
- OCR for images embedded in Word documents
- Automatic syncing instead of a manual trigger

---

## Notes

[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) records the problems worth remembering from building this — a Qdrant 401 caused by an empty environment variable, a prompt whose word "concise" collapsed every answer into one paragraph, chunk boundaries landing mid-word in a language without spaces, and the PDF library that cost 200 lines before being replaced.

[`DEPLOYMENT.md`](DEPLOYMENT.md) covers running in containers and what's missing before this could face the internet.

---

## License

MIT
