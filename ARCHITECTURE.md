# Papers Please — Architecture Reference

A technical deep-dive into every layer of the system: module responsibilities, data contracts, design decisions, and extension points.

Built by **Nirbhik Chaki** and **Prabhat Anil Bajpai** — CMR Institute of Technology, Bengaluru.

---

## Table of Contents

- [Repository Layout](#repository-layout)
- [High-Level Architecture](#high-level-architecture)
- [Module Reference](#module-reference)
  - [detector.py](#detectorpy)
  - [parser.py](#parserpy)
  - [db.py](#dbpy)
  - [embedder.py](#embedderpy)
  - [deduplicator.py](#deduplicatorpy)
  - [scorer.py](#scorerpy)
  - [tagger.py](#taggerpy)
  - [exporter.py](#exporterpy)
- [Pipeline Orchestrator](#pipeline-orchestrator)
- [Streamlit UI Pages](#streamlit-ui-pages)
- [Database Schema](#database-schema)
- [Configuration — subjects.yaml](#configuration--subjectsyaml)
- [Data Flow End-to-End](#data-flow-end-to-end)
- [Design Decisions](#design-decisions)
- [Extension Points](#extension-points)

---

## Repository Layout

```
Papers-Please/
│
├── app.py                  # Streamlit entry point — renders the home page
├── pipeline.py             # 7-step orchestrator — the only caller of all modules
├── subjects.yaml           # Config-driven subject map (145+ VTU 2022 codes)
├── requirements.txt
│
├── modules/
│   ├── detector.py         # Step 1: PDF format detection + table extraction
│   ├── parser.py           # Step 2: raw rows → structured sub_question dicts
│   ├── db.py               # Step 3: SQLite helper — schema, inserts, queries
│   ├── embedder.py         # Step 4a: Sentence-BERT singleton + encode()
│   ├── deduplicator.py     # Step 4b: centroid-based 2-pass clustering
│   ├── scorer.py           # Step 5: recency-decay scoring + marks ladder
│   ├── tagger.py           # Step 6: Ollama topic labelling with keyword fallback
│   └── exporter.py         # Step 7a: PDF cheat sheet + CSV question bank
│
├── pages/
│   ├── 1_Upload.py         # Streamlit page — file uploader + pipeline trigger
│   ├── 2_Dashboard.py      # Streamlit page — module tabs, ladder, exports
│   └── 3_Graph.py          # Streamlit page — D3.js force-directed topic graph
│
├── docs/                   # Architecture diagrams (referenced by README)
│   ├── architecture.png
│   ├── pipeline.png
│   ├── data_model.png
│   └── tech_stack.png
│
└── data/                   # Runtime data — gitignored
    ├── raw/                # Uploaded PDFs
    ├── extracted/          # Per-paper JSON debug dumps
    └── papers.db           # SQLite database
```

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Streamlit UI                       │
│   ┌──────────┐   ┌──────────────┐   ┌────────────┐  │
│   │  Upload  │   │  Dashboard   │   │   Graph    │  │
│   │  page    │   │  page        │   │   page     │  │
│   └────┬─────┘   └──────┬───────┘   └─────┬──────┘  │
└────────┼────────────────┼─────────────────┼──────────┘
         │                │                 │
         ▼                │                 │
  pipeline.run()          │                 │
         │                ▼                 ▼
         │          db.get_*()         db.get_*()
         │
  ┌──────▼────────────────────────────────────────┐
  │              pipeline.py (orchestrator)        │
  │                                               │
  │  1. detector  → (pdf_type, raw_rows)          │
  │  2. parser    → sub_question dicts            │
  │  3. db        → paper_id, sub_question rows   │
  │  4. deduplicator → canonical clusters         │
  │  5. scorer    → ranked ladder per module      │
  │  6. tagger    → topic labels                  │
  │  7. db        → persist canonical questions   │
  └───────────────────────────────────────────────┘
         │
  ┌──────▼──────┐
  │   SQLite    │  papers.db
  │  (db.py)    │
  └─────────────┘
```

The pipeline is the **single dependency hub** — no module calls another module directly. This keeps the call graph flat and each module independently testable.

---

## Module Reference

### detector.py

**Responsibility:** Given a PDF path, decide how to read it and return structured table rows.

**Public API:**
```python
def detect_and_extract(pdf_path: str) -> tuple[str, list[list[str]]]:
    # Returns: (pdf_type, rows)
    # pdf_type: "native" | "scanned"
    # rows: list of cell lists, e.g. [["1", "a", "Explain CRC...", "5", "L2", "CO3"]]
```

**Decision logic:**
```
Try pdfplumber native extraction
  → If total text chars < MIN_NATIVE_TEXT_PER_PAGE * n_pages:
      Fall back to OCR path
  → If no tables found:
      Fall back to OCR path

OCR path:
  PyMuPDF renders page at 300 DPI → grayscale NumPy array
  Tesseract PSM 6 → word bounding boxes (left, top, width, height, text, conf)
  Words filtered by conf > 30
  Words grouped into rows by vertical proximity (10px tolerance)
  Row words assigned to columns by x-position / page_width ratio:
    [0.00–0.13] → Q.No
    [0.13–0.17] → Sub
    [0.17–0.74] → Question text
    [0.74–0.83] → Marks
    [0.83–0.89] → Bloom level
    [0.89–0.98] → Course outcome
```

**Subject map loading:**
```python
# At module load time:
VTU_SUBJECT_MAP = _load_subject_map()
# Tries subjects.yaml next to project root → falls back to hardcoded dict
```

**Key constants:**
- `DPI = 300` — render resolution for OCR
- `MIN_NATIVE_TEXT_PER_PAGE = 100` — chars threshold to detect scanned pages

---

### parser.py

**Responsibility:** Convert raw cell lists from `detector.py` into clean `sub_question` dicts the DB can store.

**Public API:**
```python
def parse_rows(rows: list[list[str]], filename: str) -> tuple[dict, list[dict]]:
    # Returns: (metadata, sub_questions)
    # metadata: {subject_code, subject_name, year, month, exam_type, ...}
    # sub_questions: [{module, q_no, sub_q, text, marks, bloom, co}, ...]
```

**Row classification logic (in order):**
1. **Module header** — matches "Module – 3" or garbled variants via 3-tier fuzzy regex. Updates `current_module`.
2. **OR separator** — single cell containing "OR" or "or". Skipped.
3. **Question row** — has a valid Q.No pattern and non-empty text cell. Parsed into a sub_question dict.
4. **Continuation** — text-only row with no Q.No. Appended to the previous question's text.
5. **Ignored** — marks-only rows, page headers, blank rows.

**OCR Q.No normalisation:**
```
Pattern examples recognised:
  "1" / "Q1" / "Q.1" / "01" → module question 1
  "O22" (doubled digit) → 2
  "Qa" / "0.7" / "oO6" → parsed with fallback patterns
```

**Filename metadata extraction:**
```
Patterns: "JAN 2025 BCS502", "DEC2024_BCS501", "BCS515D MQP 1"
  → subject_code, year, month, exam_type (regular/model/MQP)
```

---

### db.py

**Responsibility:** All SQLite operations — schema creation, inserts, queries. No business logic.

**Schema:**
```sql
papers (
    id          INTEGER PRIMARY KEY,
    filename    TEXT UNIQUE,
    subject_code TEXT,
    subject_name TEXT,
    year        INTEGER,
    month       TEXT,
    exam_type   TEXT,
    pdf_type    TEXT,
    created_at  TIMESTAMP
)

sub_questions (
    id          INTEGER PRIMARY KEY,
    paper_id    INTEGER REFERENCES papers(id),
    module      INTEGER,
    q_no        TEXT,
    sub_q       TEXT,
    text        TEXT,
    marks       INTEGER,
    bloom_level TEXT,
    course_outcome TEXT
)

canonical_questions (
    id              INTEGER PRIMARY KEY,
    subject_code    TEXT,
    module          INTEGER,
    representative_text TEXT,
    topic_label     TEXT,
    avg_marks       REAL,
    frequency       INTEGER,
    frequency_pct   REAL,
    weighted_score  REAL,
    full_coverage   INTEGER,
    expected_marks  REAL,
    rank            INTEGER
)

appearances (
    id                  INTEGER PRIMARY KEY,
    canonical_question_id INTEGER REFERENCES canonical_questions(id),
    sub_question_id     INTEGER REFERENCES sub_questions(id),
    paper_id            INTEGER,
    year                INTEGER,
    q_no                TEXT,
    sub_q               TEXT,
    marks               INTEGER
)
```

**Key functions:**
```python
get_conn(db_path)                    # Returns connection with WAL + foreign keys
insert_paper(db_path, meta) → int   # Returns paper_id or None if duplicate
insert_sub_questions(...)
delete_sub_questions_for_paper(...)  # Used by force=True re-processing
get_sub_questions_for_module(...)    # Main query for deduplication
insert_canonical_questions(...)
get_canonical_questions(...)         # Used by Dashboard + exporter
get_all_subjects(db_path)           # Returns [{subject_code, subject_name, count}, ...]
```

**Idempotency contract:** `papers.filename` has a UNIQUE constraint. `insert_paper` returns `None` on duplicate, triggering a skip in the pipeline. When `force=True`, existing sub-questions are deleted first, then re-inserted fresh.

---

### embedder.py

**Responsibility:** Singleton wrapper around `SentenceTransformer`. Ensures the model is loaded once and reused.

**Public API:**
```python
def encode(texts: list[str]) -> np.ndarray:
    # Returns L2-normalised embeddings, shape (N, 384)
```

**Model:** `paraphrase-MiniLM-L6-v2`

Why this model over `all-MiniLM-L6-v2`:
- Trained specifically on **paraphrase pairs** from MSMARCO, QQP, and other datasets
- "Explain CRC" ↔ "Describe CRC encoder operation with diagram" → similarity ~0.82 (vs ~0.72 with the general model)
- Still CPU-friendly (~90 MB download, ~50ms for 50 questions on a laptop)

All embeddings are **L2-normalised at encode time**, so `cos_sim(a, b) = dot(a, b)` — no division needed during clustering.

---

### deduplicator.py

**Responsibility:** Group sub-questions from the same (subject, module) across all papers into canonical clusters.

**Public API:**
```python
def deduplicate(
    sub_questions: list[dict],
    threshold: float = 0.70,
) -> list[dict]:
    # Returns canonical question dicts:
    # [{representative_text, avg_marks, appearances: [...]}]
```

**Algorithm — Two-Pass Centroid Clustering:**

```
PRE-PROCESSING:
  1. Filter texts shorter than MIN_TEXT_LENGTH (12 chars) — discards OCR garbage
  2. Run _clean_for_embed() on each text:
       - Strip leading sub-question labels ("a.", "Q.3", pipes, underscores)
       - Strip trailing punctuation noise
       - Fix OCR run-together prefixes ("AExplain" → "Explain")
  3. Encode all cleaned texts → L2-normalised embeddings matrix E (N × 384)

PASS 1 — GREEDY SEEDING:
  clusters = []
  centroids = []
  for i in range(N):
      vec = E[i]
      best_sim, best_c = max over all centroids of dot(vec, centroid)
      if best_sim >= threshold:
          clusters[best_c].append(i)
          centroid = incremental_mean(old_centroid, vec, n_members)
          centroid = centroid / norm(centroid)   # keep unit length
      else:
          clusters.append([i])
          centroids.append(vec.copy())

PASS 2 — REFINEMENT:
  centroids = [mean(E[idxs]) / norm for idxs in clusters]   # recompute from scratch
  C = stack(centroids)   # (K × 384) matrix
  sims = E @ C.T         # (N × K) — all similarities in one matmul
  new_clusters = [[] for k in K] + []   # extra slots for new singletons
  for i in range(N):
      best_c = argmax(sims[i])
      if sims[i, best_c] >= threshold:
          new_clusters[best_c].append(i)
      else:
          new_clusters.append([i])   # forced singleton
  clusters = [c for c in new_clusters if c]   # drop empties

POST-PROCESSING:
  For each cluster:
      representative_text = most recent + longest question text
      avg_marks = mean(marks) across appearances
      appearances = [{sub_question_id, paper_id, year, q_no, sub_q, marks}]
```

**Why two passes:** The greedy pass is order-dependent — an early question can "claim" a centroid position that later questions would have been better placed in. The refinement pass corrects this by reassigning everything against fresh, unbiased centroids.

**Threshold = 0.70** was empirically tuned on ~200 real VTU questions:
- At 0.80+: "explain X" and "describe X with diagram" remain separate clusters (~15% false negatives)
- At 0.70: same pair merges correctly; "X" and "Y" from the same module remain separate
- At 0.60-: unrelated topics within the same module start merging (~5% false positives)

---

### scorer.py

**Responsibility:** Given a list of canonical question dicts, return a sorted, scored ladder per module.

**Public API:**
```python
def build_module_ladders(
    canonical_questions: list[dict],
    total_papers: int,
    current_year: int,
) -> dict[int, list[dict]]:
    # Returns {module_no: [step_dicts sorted by weighted_score desc]}
```

**Scoring formula:**
```python
DECAY = 0.85

weighted_score = sum(
    DECAY ** (current_year - appearance["year"])
    for appearance in canonical_question["appearances"]
    if appearance["year"]
)

frequency_pct = len(appearances) / total_papers
expected_marks = frequency_pct * avg_marks
```

**Ladder construction:**
```python
# Sort by weighted_score descending within each module
# Accumulate expected_marks top-down
# Mark full_coverage=True when cumulative_expected >= MAX_MODULE_MARKS (20)
```

**format_years / format_appearances** helpers format display strings like "Jan 2025, Dec 2024" and "Q3a (5M, 2024)" for the dashboard and CSV.

---

### tagger.py

**Responsibility:** Assign a short human-readable topic label (3-5 words) to each canonical question.

**Public API:**
```python
def label_questions(questions: list[dict]) -> list[dict]:
    # Adds "topic_label" key to each question dict in-place
```

**Three-tier fallback:**

```
Tier 1 — Ollama preferred model (phi3:mini or llama3.2:1b):
  Prompt: "Give a 3-5 word topic label for this VTU exam question: <text>"
  If Ollama not running → TimeoutError → fall through

Tier 2 — Any available Ollama model:
  List models with ollama.list(), try the first available
  If no models → fall through

Tier 3 — Keyword frequency fallback (no LLM):
  Tokenise question text → strip stopwords + OCR noise words
  Return top 3 content words joined by spaces
  Example: "Explain CRC encoder operation" → "CRC encoder operation"
```

The fallback means the pipeline **never fails** due to Ollama being absent. Label quality degrades gracefully.

---

### exporter.py

**Responsibility:** Generate exportable outputs from the scored ladder.

**Public API:**
```python
def generate_cheat_sheet(
    subject_name, subject_code,
    module_ladders, total_papers,
) -> bytes:   # PDF bytes

def generate_csv(
    subject_name, subject_code,
    module_ladders, total_papers,
) -> str:   # CSV string
```

**PDF layout (fpdf2):**
- Header with subject name, code, total papers analysed, generation date
- One section per module, sorted by priority rank
- Each row: rank, topic label, question text (truncated at 120 chars), avg marks, frequency, years seen
- Full coverage marker `[✓ Full Coverage]` at the cutoff point

**CSV columns:**
```
Module, Priority Rank, Topic Label, Question Text, Avg Marks,
Times Repeated, Total Papers, Frequency %, Years Seen,
Expected Marks, Full Coverage
```

Sorted by Module then Priority Rank — designed to be importable directly into Google Sheets or Excel for further filtering.

---

## Pipeline Orchestrator

`pipeline.py` is the **only file that imports from multiple modules**. All modules are isolated from each other.

```python
def run(
    pdf_paths: list[str],
    db_path: str,
    progress_cb: Callable = None,
    force: bool = False,
) -> dict:
```

**Step sequence for each PDF:**

```
Step 1 — detector.detect_and_extract(pdf_path)
         → pdf_type: "native" | "scanned"
         → raw_rows: list[list[str]]

Step 2 — parser.parse_rows(raw_rows, filename)
         → meta: {subject_code, year, month, ...}
         → sub_qs: [{module, q_no, sub_q, text, marks, ...}]

Step 3 — db.insert_paper(meta) → paper_id
         if paper_id is None: skip (already in DB)
         if force: db.delete_sub_questions_for_paper(paper_id)
         db.insert_sub_questions(paper_id, sub_qs)

Step 4 — For each (subject_code, module) pair in the DB:
         raw = db.get_sub_questions_for_module(subject_code, module)
         clusters = deduplicator.deduplicate(raw)

Step 5 — ladder = scorer.build_module_ladders(clusters, total_papers)

Step 6 — tagger.label_questions(all_clusters)

Step 7 — db.delete_canonical_questions(subject_code)
         db.insert_canonical_questions(subject_code, ladders)
```

**force=True** re-processes an already-uploaded paper: deletes its sub-questions and re-inserts from scratch. All canonical questions for that subject are also rebuilt.

**progress_cb** receives a string message at each step — used by the Streamlit Upload page to update the progress bar in real time.

---

## Streamlit UI Pages

### app.py (Home)
Renders the landing page with project description, quick-start instructions, and navigation hints. No pipeline calls.

### pages/1_Upload.py
- `st.file_uploader` with `accept_multiple_files=True`, `type=["pdf"]`
- Saves uploaded files to `data/raw/`
- Calls `pipeline.run()` with a `st.progress` callback
- Shows per-file status (skipped / processed / error)
- "Force re-process" toggle for re-uploading papers

### pages/2_Dashboard.py
- Queries `db.get_all_subjects()` → renders a selectbox
- Queries `db.get_canonical_questions(subject_code)` → builds `module_ladders` dict
- Renders `st.tabs` (one per module)
- Each tab: `st.dataframe` with the ladder + `st.metric` for coverage
- Export section: two `st.download_button` — one for PDF, one for CSV

### pages/3_Graph.py
- Queries canonical questions for the selected subject
- Builds a node/edge graph where questions sharing a module are connected
- Renders an interactive D3.js force-directed graph via `st.components.v1.html`
- Node size = frequency, node colour = module, edges = co-appearance in same module

---

## Database Schema

```
papers
  id ──────────────────────┐
  filename (UNIQUE)        │
  subject_code             │
  subject_name             │
  year                     │
  month                    │
  exam_type                │
  pdf_type                 │
  created_at               │
                           │
sub_questions              │
  id ──────────────────────┼──────────────────┐
  paper_id ────────────────┘                  │
  module                                      │
  q_no, sub_q                                 │
  text                                        │
  marks, bloom_level, course_outcome          │
                                              │
canonical_questions                           │
  id ──────────────────────────────┐          │
  subject_code                     │          │
  module                           │          │
  representative_text              │          │
  topic_label                      │          │
  avg_marks                        │          │
  frequency, frequency_pct         │          │
  weighted_score                   │          │
  full_coverage, expected_marks    │          │
  rank                             │          │
                                   │          │
appearances                        │          │
  canonical_question_id ───────────┘          │
  sub_question_id ────────────────────────────┘
  paper_id
  year, q_no, sub_q, marks
```

**Rebuild strategy:** Canonical questions and appearances are **fully deleted and rebuilt** whenever new papers are added to a subject. This ensures the frequency, weighted_score, and rankings are always computed over the complete dataset.

---

## Configuration — subjects.yaml

```yaml
# Format: "SUBJECT_CODE": "Subject Name"
# The app loads this at startup via modules/detector._load_subject_map()
# Falls back to the hardcoded dict if the file is missing or unparseable.

BCS301: Mathematics for Computer Science (CSE/ISE)
BCS302: Digital Design and Computer Organization
# ... 145+ entries organised by semester and branch
```

**Loading sequence:**
```python
yaml_path = Path(__file__).parent.parent / "subjects.yaml"
raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
loaded = {str(k).upper(): str(v) for k, v in raw.items()
          if not str(k).startswith("#")}
```

**Comment lines** (lines starting with `#`) are filtered at the YAML level — `yaml.safe_load` treats them as YAML comments and they never appear in the parsed dict.

---

## Data Flow End-to-End

```
User uploads  ──► data/raw/BCS502_JAN2025.pdf
                       │
                       ▼
             detector.detect_and_extract()
                  ├─ pdfplumber (native)
                  └─ PyMuPDF + Tesseract (scanned)
                       │
                       ▼ raw_rows: [["1","a","Explain CRC...","5","L2","CO3"], ...]
                       │
             parser.parse_rows()
                       │
                       ▼ sub_qs: [{module:2, q_no:"1", sub_q:"a",
                       │           text:"Explain CRC encoder...", marks:5}, ...]
                       │
             db.insert_paper() + db.insert_sub_questions()
                       │
                       ▼ paper stored, sub_questions rows created
                       │
             db.get_sub_questions_for_module("BCS502", 2)
                  [Aggregates across ALL papers for this subject+module]
                       │
                       ▼ [{id, text, marks, year, paper_id, q_no, sub_q}, ...]
                       │
             deduplicator.deduplicate()
                  embedder.encode() → L2-norm embeddings
                  Pass 1: greedy centroid clustering
                  Pass 2: refinement via centroid matrix multiply
                       │
                       ▼ canonical clusters: [{representative_text, appearances:[...]}, ...]
                       │
             scorer.build_module_ladders()
                       │
                       ▼ {2: [{rank:1, weighted_score:3.2, expected_marks:4.1, ...}, ...]}
                       │
             tagger.label_questions()
                  → Ollama / keyword fallback
                       │
                       ▼ topic_label added to each cluster
                       │
             db.insert_canonical_questions()
                       │
                       ▼ stored in canonical_questions + appearances tables
                       │
             Dashboard reads db.get_canonical_questions("BCS502")
             exporter generates PDF / CSV
                       │
                       ▼
             User downloads cheat sheet or question bank
```

---

## Design Decisions

### Why SQLite and not PostgreSQL?
Single-user, local-first app. No concurrent writes. No network. SQLite with WAL mode handles all requirements with zero setup. The entire database is a single file — easy to back up, share, or delete.

### Why Streamlit and not Flask + React?
The goal was a functional tool, not a product. Streamlit delivers a working dashboard in ~200 lines of Python with no JavaScript, no templates, no HTTP routing. The tradeoff (limited interactivity, no real-time push) is acceptable for an offline analysis tool.

### Why hardcoded column proportions for OCR?
VTU CBCS question papers have a remarkably consistent layout (all A4, same column structure since 2017). Auto-detecting columns from word gap analysis failed on pages with headers, footers, and partial rows. Fixed proportional splits calibrated from 20+ real papers are more reliable than a general-purpose solution for this specific domain.

### Why paraphrase-MiniLM over all-MiniLM?
`all-MiniLM-L6-v2` is trained on diverse web text for semantic similarity. `paraphrase-MiniLM-L6-v2` is trained on **parallel paraphrase corpora** (MSMARCO, QQP, PAWS). Academic exam questions are essentially paraphrases of the same concept — the paraphrase-tuned model has a structural advantage for this task.

### Why greedy clustering over k-means or DBSCAN?
- k-means requires knowing K upfront — the number of unique topics in a module is unknown
- DBSCAN requires two hyperparameters (eps, min_samples) that don't generalise across modules with 5 vs 50 questions
- Greedy centroid clustering is single-pass, O(N × K), and requires only one threshold parameter

The 2-pass refinement added later corrects the main weakness (order-dependence) without changing the algorithm's core simplicity.

### Why recency-decay scoring?
Exams are not uniformly distributed in time. VTU course content evolves — topics added to recent syllabi appear more in recent papers. A question asked 3 times in the last 3 years is a stronger signal than one asked 3 times between 2015 and 2019. The exponential decay model (DECAY=0.85, same as used in ELO rating systems and email inbox aging) captures this naturally.

---

## Extension Points

### Adding new subject codes
Edit `subjects.yaml`. No code changes needed. The app reads the file at startup.

### Adding a new VTU semester or branch
Add entries to `subjects.yaml` under a new comment block. The subject code prefix determines the branch — the app has no hardcoded branch logic beyond the map.

### Supporting non-VTU papers
1. Implement a new extraction strategy in `detector.py` returning the same `list[list[str]]` format
2. Implement new filename metadata patterns in `parser._parse_filename()`
3. Add subject codes to `subjects.yaml`
No other files need changing.

### Adding a new export format
Add a new function to `exporter.py` with the same signature pattern as `generate_csv` / `generate_cheat_sheet`, then add a `st.download_button` in `pages/2_Dashboard.py`.

### Swapping the embedding model
Change the model name string in `embedder.py`. The rest of the pipeline is model-agnostic — it only sees normalised float arrays.

### Replacing Ollama with a different LLM
Modify `tagger.py`'s Tier 1 / Tier 2 blocks. The Tier 3 keyword fallback is unaffected.
