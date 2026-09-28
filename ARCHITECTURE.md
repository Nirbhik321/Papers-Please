# Papers Please — Architecture Reference

A technical deep-dive into every layer of the system: how requests flow, what each module does, how uploads are kept safe, and why things are built the way they are.

Built by **Nirbhik Chaki** and **Prabhat Anil Bajpai** — CMR Institute of Technology, Bengaluru.

---

## Table of Contents

- [Repository Layout](#repository-layout)
- [High-Level Architecture](#high-level-architecture)
- [The Life of an Upload](#the-life-of-an-upload)
- [Upload Security](#upload-security)
- [Publishing and Snapshots](#publishing-and-snapshots)
- [Website](#website)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Analysis Modules](#analysis-modules)
- [Hosting and Keep-Alive](#hosting-and-keep-alive)
- [Configuration — subjects.yaml](#configuration--subjectsyaml)
- [Design Decisions](#design-decisions)
- [Extension Points](#extension-points)

---

## Repository Layout

```
Papers-Please/
├── web/                        # Next.js website (deployed on Vercel)
│   └── src/
│       ├── app/
│       │   ├── page.tsx              # Home — search, filters, just-added feed
│       │   ├── s/[code]/             # Subject page, studied tracking, topic graph
│       │   ├── upload/               # Upload flow with live progress + confirm step
│       │   ├── admin/                # Moderation (not linked, sign-in required)
│       │   ├── how-it-works/         # Explains ranking and safety
│       │   └── api/revalidate/       # On-demand refresh hook called by the API
│       ├── components/               # Header, theme toggle, icons
│       └── lib/                      # API client, types, formatting
│
├── server/                     # FastAPI app + worker (deployed on Render)
│   ├── main.py                 # HTTP routes
│   ├── config.py               # Settings from environment variables
│   ├── db.py                   # Schema (SQLAlchemy Core) — SQLite locally, Postgres in production
│   ├── storage.py              # Private storage for original PDFs (disk or Supabase Storage)
│   ├── security.py             # Upload checks, rate limiting, Turnstile, hashing
│   ├── sandbox.py              # Reads untrusted PDFs in a locked-down child process
│   ├── ingest.py               # Upload lifecycle, duplicate detection, moderation actions
│   ├── analysis.py             # Rebuilds a subject and publishes its snapshot
│   ├── worker.py               # Single background thread running heavy jobs
│   ├── catalog.py              # Subject list + exam-session helpers
│   ├── auth.py                 # Moderator authentication
│   ├── cli.py                  # seed / rebuild / status
│   └── tests/                  # API + safety tests
│
├── modules/                    # The analysis pipeline (pure Python, framework-free)
│   ├── detector.py             # PDF type detection + table extraction (pdfplumber / OCR)
│   ├── parser.py               # Raw rows → structured sub-questions
│   ├── embedder.py             # Sentence-BERT on ONNX Runtime
│   ├── deduplicator.py         # Two-pass centroid clustering
│   ├── scorer.py               # Recency-decay scoring + marks ladder
│   ├── tagger.py               # Topic labels (Ollama if present, phrase extraction otherwise)
│   └── exporter.py             # A4 cheat sheet PDF + CSV question bank
│
├── supabase/migrations/        # Postgres schema with RLS + keep-alive cron jobs
├── subjects.yaml               # 145+ VTU 2022-scheme subject codes
├── Dockerfile · render.yaml    # API deployment
└── data/                       # Local runtime data — gitignored
```

---

## High-Level Architecture

```
                 ┌───────────────────────────────┐
  Students ────► │  Next.js site (Vercel)         │  pages pre-rendered, refreshed on demand
                 │  Home · Subject · Upload · …   │  navigation and interaction in the browser
                 └──────┬───────────────┬────────┘
             reads      │               │ uploads, status polling, moderation
       (build + ISR)    ▼               ▼
                 ┌───────────────────────────────┐
                 │  FastAPI (Render, 1 process)   │
                 │  public reads: snapshots only  │
                 │  uploads: quick checks → queue │
                 │  ┌──────────────────────────┐  │
                 │  │ worker thread, 1 job at  │──┼──► sandbox child process per PDF
                 │  │ a time: read → match →   │  │    (no secrets, time/memory limits)
                 │  │ publish                  │  │
                 │  └──────────────────────────┘  │
                 └──────┬───────────────┬────────┘
                        ▼               ▼
              Supabase Postgres   Supabase Storage (private "uploads" bucket)
              (RLS on every table)
```

Two rules shape everything:

1. **Reading never does work.** Every subject has a precomputed *snapshot* (the JSON the page renders, the cheat-sheet PDF and the CSV). A student opening a subject gets a pre-rendered page; the API only ever returns stored bytes.
2. **Uploads are hostile until proven otherwise.** Files are checked before they're accepted, parsed only inside a sandbox, and can't change what students see until they pass duplicate and sanity checks — or a moderator approves them.

---

## The Life of an Upload

```
POST /api/uploads ──► quick checks (size, %PDF- header, rate limit, Turnstile, block list)
        │             exact-duplicate check by SHA-256  ──► 409 "already in the bank"
        ▼
 store original under its hash, create paper (status=processing)   ──► returns {id, token}
        │
 worker: process_paper ── sandbox: pages ≤ 6, not encrypted, sane page size,
        │                  detector → parser → sub_questions
        │── fewer than 5 questions or 3 modules ──► rejected ("not a question paper"), file deleted
        ▼
 status=awaiting_confirmation  (the uploader sees what was detected + 3 sample questions)
        │
 POST /api/uploads/{id}/confirm  (subject code, paper type, month, year — validated)
        ▼
 worker: match_paper
        ├─ subject not in subjects.yaml ─────────────────┐
        ├─ fewer than 8 questions / 4 modules ────────────┤
        ├─ exam session already has a live paper ─────────┼──► status=review (moderator decides)
        ├─ ≥ 90% of questions match a live paper ─────────┘
        └─ otherwise ──► status=approved ──► rebuild subject ──► revalidate pages ──► Live
```

The uploader polls `GET /api/uploads/{id}` with their private token (returned only to them) and watches the steps: *Uploaded → Read safely → Confirm details → Matched → Live*.

**Exam sessions.** VTU runs two semester-end sessions a year, labelled inconsistently ("Dec 2024", "Jan 2025", "Dec 2024–Jan 2025"). `catalog.normalize_session` folds Nov/Dec/Jan/Feb onto *January* and May–Aug onto *July*, and `session_key` = `BCS502:see:2025:jan`. A partial unique index allows **one live paper per session**, so the same exam can never be counted twice. Model papers have no session key (several sets per year are legitimate); near-duplicate detection still catches re-uploads of them.

---

## Upload Security

| Threat | Defence |
|---|---|
| Parser exploits, decompression bombs, huge page images | PDFs are opened only in `sandbox.py`: a separate process per file with a scrubbed environment (no DB URL or keys), wall-clock timeout, and on Linux CPU / 1.5 GB address-space / file-size rlimits. PIL's pixel limit guards image bombs. Pages > 2000 pt, > 6 pages or encrypted files are refused. |
| Oversized uploads / disk filling | `Content-Length` checked before reading; body read with a hard cap (10 MB); `%PDF-` header required. |
| Path traversal via filenames | The uploader's filename is only ever displayed (sanitised). Files are stored under `papers/<hash[:2]>/<sha256>.pdf`; the local storage backend refuses keys that escape its folder. |
| Serving malicious files to students | Originals are **never served**. Students only get extracted text and PDFs we generate. |
| Duplicate / inflated counts | Exact duplicates by SHA-256; one live paper per exam session (unique index); ≥ 90% question overlap with a live paper → review. |
| Fake or junk papers | Structural checks (questions, modules found) reject non-papers and hold partial scans for review; unknown subject codes go to review. |
| Spam and abuse | Cloudflare Turnstile per upload, 10 uploads/hour per uploader, moderators can block an uploader. Uploaders are identified by an HMAC of their IP (the IP itself is never stored). |
| Stored XSS via question text | React escapes all text; no `dangerouslySetInnerHTML` with data. Topic labels are length-limited plain text. |
| Unauthorised moderation | Every `/api/admin/*` route requires a moderator: a Supabase Auth session whose email is in `ADMIN_EMAILS`, or the `ADMIN_TOKEN` secret. |
| Reading the database through Supabase's public API | Row-level security is enabled on every table with no policies; only the API server (table owner) can read or write. |
| Someone else confirming your upload | Status and confirm endpoints require the upload's random token; only its SHA-256 is stored. |

Limits worth knowing: the sandbox is a process boundary, not a container, and rate limiting is in memory (fine for one server process).

---

## Publishing and Snapshots

`analysis.rebuild_subject(code)` runs on the worker thread whenever a subject's set of live papers changes (auto-approval, approve, replace, reject/take-down, delete, or `cli rebuild`):

1. Load all approved papers for the subject and their sub-questions.
2. For each module: `deduplicator.deduplicate` → `scorer.score_canonicals` (single-paper subjects are ranked by marks instead).
3. **Stable topic keys.** Each new group takes the key (and label) of the previous build's topic that shared the most sub-questions, so a student's "studied" ticks — stored in their browser by topic key — survive new papers arriving. `--relabel` regenerates labels.
4. Label new topics with `tagger`.
5. Write `topics` / `topic_appearances`, then one `subject_snapshots` row: the page JSON, the cheat-sheet PDF and the CSV.
6. POST `REVALIDATE_URL` so Vercel refreshes `/` and `/s/<code>` on their next visit.

Snapshot JSON (abridged):

```json
{
  "code": "BCS502", "name": "Computer Networks", "paperCount": 4, "moduleMarks": 20,
  "sessions": [{"id": 9, "label": "Jan 2025", "short": "Jan 25", "type": "see", "source": "scanned"}],
  "modules": [{
    "no": 1, "fullAt": 3,
    "ladder": [{"rank": 1, "label": "Data Communications", "cumulative": 8.0, "full": false}],
    "topics": [{
      "key": "3f9a1c2b7d0e", "rank": 1, "label": "Data Communications",
      "text": "What is data communication? …", "frequency": 3, "frequencyPct": 0.75,
      "avgMarks": 8.0, "expectedMarks": 6.0, "sessions": [9, 2, 3],
      "wordings": [{"session": 9, "where": "Q1a", "marks": 10, "text": "Define data communications …"}]
    }]
  }]
}
```

---

## Website

Next.js (App Router) with Tailwind, desktop-first.

| Route | Rendering | Notes |
|---|---|---|
| `/` | Static, ISR (5 min + on demand) | Search filters in the browser as you type; `/` focuses search; matches in the subject list with no papers link to upload. |
| `/s/[code]` | Static per subject (`generateStaticParams`), ISR | Module tabs, topic cards, "Mark studied" (localStorage), coverage meter, marks ladder, papers list. The graph view (d3-force) is a separate chunk loaded only when opened. |
| `/upload` | Static shell, client-side flow | Drag-and-drop, Turnstile, polling, confirm form. The visit's uploads survive a refresh (sessionStorage). |
| `/admin` | Client only, `noindex` | Sign in with Supabase Auth (or the admin token locally); queues by status; side-by-side duplicate comparison; approve / replace / reject / reprocess / delete / block. |
| `/api/revalidate` | Route handler | Bearer-secret protected; calls `revalidatePath` for the paths the API sends. |

If the API is unreachable at build time the build still succeeds with empty data and ISR fills pages in; at runtime a failed refresh keeps serving the last good page.

Dark mode follows the system setting, can be toggled, and is applied by an inline script before first paint (no flash).

---

## API Reference

| Method & path | Who | Purpose |
|---|---|---|
| `GET /healthz` | anyone | Render health check; touches nothing |
| `GET /api/keepalive` | anyone | Cron ping target; runs `SELECT 1` so the database counts as active |
| `GET /api/stats`, `/api/subjects`, `/api/catalog`, `/api/recent` | anyone | Lists for the home page |
| `GET /api/subjects/{code}` | anyone | Snapshot JSON |
| `GET /api/subjects/{code}/cheatsheet.pdf`, `/questions.csv` | anyone | Downloads |
| `POST /api/uploads` | anyone (rate-limited, Turnstile) | Returns `{id, token}`; `409` for exact duplicates |
| `GET /api/uploads/{id}` | uploader (`X-Upload-Token`) | Status, detected metadata, preview |
| `POST /api/uploads/{id}/confirm` | uploader | Subject + session confirmation |
| `GET /api/admin/me`, `/api/admin/papers[?status=]`, `/api/admin/papers/{id}` | moderator | Queues, detail with duplicate comparison |
| `POST /api/admin/papers/{id}/approve · reject · replace · reprocess` | moderator | Decisions |
| `PATCH /api/admin/papers/{id}` · `DELETE /api/admin/papers/{id}` | moderator | Fix metadata · remove |
| `POST /api/admin/uploaders/{hash}/block` · `/api/admin/subjects/{code}/rebuild` | moderator | Abuse · maintenance |

Interactive docs: `/api/docs`.

---

## Database Schema

```
papers                      one row per upload
  id, status, stage, status_reason
  subject_code, subject_name, exam_year, exam_month, paper_type, session_key
  filename (display only), content_hash (UNIQUE), storage_key
  pdf_type, page_count, question_count, modules_found, detected (JSON)
  upload_token_hash, uploader_hash, reviewed_by, reviewed_at, created_at, updated_at
  UNIQUE (session_key) WHERE status = 'approved'

sub_questions               questions extracted from a paper (cascade-deleted with it)
  id, paper_id → papers, module_no, q_no, sub_q, is_or_alt, text, marks, bloom_level, course_outcome

topics                      groups of the same question across papers, per subject + module
  id, subject_code, module_no, stable_key, label, representative_text,
  avg_marks, frequency, weighted_score, last_seen_year

topic_appearances           topic ↔ sub_question
subject_snapshots           published data: data (JSON), cheatsheet_pdf, questions_csv, counts, updated_at
blocked_uploaders           uploader_hash, reason, blocked_by
```

Statuses: `processing → awaiting_confirmation → processing(matching) → approved | review`, plus `rejected` and `failed`. Topics and snapshots are rebuilt from scratch for a subject whenever its live papers change.

`server/db.py` defines the schema once for both SQLite (local) and Postgres; `supabase/migrations/20260928000000_schema.sql` mirrors it for Supabase and adds RLS and the private storage bucket.

---

## Analysis Modules

### detector.py
Given a PDF path, decides how to read it and returns table rows (`list[list[str]]`).
- **Native PDFs:** `pdfplumber` table extraction.
- **Scanned PDFs** (under 100 chars of text, or no tables): PyMuPDF renders each page at 300 DPI; Tesseract (PSM 6) returns word boxes; words are grouped into rows by vertical position and bucketed into fixed VTU columns — Q.No 0–13%, Sub 13–17%, Text 17–74%, Marks 74–83%, Bloom 83–89%, CO 89–100% of page width.
- **Metadata:** `parse_filename_metadata` and `parse_content_metadata` find the subject code (`SUBJECT_CODE_RE` — every 2022-scheme code such as BCS502, BIS601, BAI515B, BMATM101), month and year.

### parser.py
Turns rows into sub-questions: module headers (strict + fuzzy regex for garbled OCR), OR rows skipped, continuation lines joined, garbled question numbers ("O22" → 2), marks/Bloom/CO scanned from all right-hand cells, whitespace folded.

### embedder.py
`paraphrase-MiniLM-L6-v2` run with **ONNX Runtime** + the `tokenizers` library: tokenise (max 128 tokens) → model → mean pooling over the attention mask → L2 normalise, so cosine similarity is a dot product. Output matches the sentence-transformers/PyTorch version to within 1e-7, with a ~100 MB install instead of ~2 GB. The model files are baked into the Docker image.

### deduplicator.py
Two-pass centroid clustering at cosine ≥ 0.70 over one subject+module across all papers:
1. **Greedy pass:** each question joins the most similar cluster centroid (incremental mean, re-normalised) or starts a new cluster.
2. **Refinement pass:** centroids recomputed from scratch; every question reassigned to its nearest centroid in one matrix multiply (below threshold → singleton). This removes the greedy pass's order-dependence.

The representative wording is the most recent, longest one. OCR noise (leading labels, pipes, run-together prefixes) is stripped before embedding.

### scorer.py
`weighted_score = Σ 0.85^(this_year − paper_year)` over the distinct papers a topic appeared in; `expected_marks = (papers it appeared in / total papers) × average marks`. The marks ladder accumulates expected marks down the ranking until the module's 20 marks are covered.

### tagger.py
Short topic labels. Uses a local Ollama model if one is running; otherwise (always, on the free server) pulls the subject of the question out of its best wording: prefers well-formed questions over OCR fragments, strips instruction words ("Explain the…", "What is…", "with a neat diagram"), list markers and filler, and keeps up to six words in title case (acronyms like TCP/IP untouched).

### exporter.py
- **Cheat sheet:** a one-page A4 PDF (fpdf2) — for each module, the top three topics with a frequency square (red = most papers, amber = half or more, outline = occasional), the question, papers seen, usual marks, and the ladder result ("Top 3 → full 20M").
- **CSV question bank:** Module, Priority Rank, Topic Label, Question Text, Avg Marks, Times Repeated, Total Papers, Frequency %, Years Seen, Expected Marks, Full Coverage.

---

## Hosting and Keep-Alive

| Piece | Where | Free-tier notes |
|---|---|---|
| Website | Vercel | Static pages + ISR |
| API + worker | Render (Docker, free) | 512 MB RAM → ONNX, one worker thread, one PDF at a time; 750 h/month covers one always-on service |
| Database, file storage, moderator login | Supabase | Postgres via the **session pooler** (Render can't reach the IPv6-only direct host) |

Render puts free services to sleep after 15 minutes without traffic, and Supabase pauses free projects after a week without database activity. `supabase/migrations/20260928000100_keepalive_cron.sql` schedules, with `pg_cron` + `pg_net`:

- `keep-render-awake` — `*/6 * * * *`: GET `https://<service>.onrender.com/api/keepalive`, which runs `SELECT 1` — so one ping keeps both Render and Supabase awake (cron works in whole minutes, so 6 minutes stands in for 6½).
- `clear-cron-history` — `0 3 */3 * *`: deletes `cron.job_run_details` rows older than a day, so the history table stays small. `pg_net` removes its own stored responses after 6 hours.

---

## Configuration — subjects.yaml

```yaml
# Format: SUBJECT_CODE: Subject Name — read at startup by modules/detector._load_subject_map()
BCS502: Computer Networks
BIS601: Full Stack Development
```

Adding a subject needs no code changes. A code missing from the file can still be uploaded, but it goes to moderator review.

---

## Design Decisions

### Why precomputed snapshots?
Reads outnumber uploads by orders of magnitude. Computing a subject's ranking takes seconds of CPU and an embedding model; serving a stored JSON takes microseconds. Doing the work once per change, on the worker, means page speed doesn't depend on the free server's CPU.

### Why Next.js with pre-rendering instead of a pure client-side app?
Pure client-side rendering shows a spinner while JavaScript downloads and then fetches data, and search engines see an empty page — and "BCS502 important questions" is exactly what students search for. Pre-rendered pages paint immediately and are indexable; after the first load, tabs, filters, studied ticks and navigation all happen in the browser.

### Why keep the pipeline in Python behind FastAPI?
The extraction and NLP pipeline was already written and tuned in Python; FastAPI exposes it with typed request models and minimal overhead. Streamlit re-ran the whole page on the server for every click, which is what made the old UI feel slow.

### Why ONNX Runtime instead of PyTorch?
Same model, same numbers, a fraction of the memory — the difference between fitting in Render's free 512 MB and not.

### Why one worker thread?
Memory. One PDF read and one subject rebuild at a time keeps peak usage flat. Jobs are recoverable: on startup every paper still marked `processing` is re-queued.

### Why hardcoded column proportions for OCR?
VTU CBCS papers have a consistent layout. Auto-detecting columns from word gaps failed on pages with headers and footers; fixed proportional splits calibrated on real papers are more reliable for this domain.

### Why paraphrase-MiniLM over all-MiniLM?
Exam questions are paraphrases of the same concept; the paraphrase-trained model scores "Explain CRC" vs "Describe the CRC encoder with a diagram" much higher.

### Why greedy clustering over k-means or DBSCAN?
The number of topics per module is unknown (rules out k-means) and module sizes vary too much for fixed DBSCAN parameters. Greedy centroid clustering needs one threshold; the refinement pass fixes its order-dependence.

### Why recency decay?
Syllabi drift. A topic asked in each of the last three sessions is a stronger signal than one asked three times years ago.

---

## Extension Points

- **New subjects / branches:** add lines to `subjects.yaml`.
- **Better topic labels:** implement a hosted-LLM tier in `tagger.generate_topic_label` (keep the phrase fallback), then `python -m server.cli rebuild --relabel`.
- **Non-VTU papers:** new extraction strategy in `detector.py` returning the same row format, plus metadata patterns and subject codes.
- **New export format:** add a generator to `exporter.py`, store it in `subject_snapshots` from `analysis._exports`, and add a download route.
- **Different embedding model:** change `_REPO` in `embedder.py` (needs an ONNX export) and re-check `SIMILARITY_THRESHOLD`.
- **Scaling beyond one server:** move rate limiting to Postgres/Redis and the job queue to a table with `SELECT … FOR UPDATE SKIP LOCKED`, then run separate API and worker processes.
