# Papers Please — Complete Project Documentation

> **Purpose:** A Streamlit web app that ingests VTU (Visvesvaraya Technological University) past exam question papers (PDFs), extracts every sub-question, groups semantically identical questions across years, ranks topics by repeat frequency and recency, and shows a "marks you can lock in" ladder per module. It can also export a printable cheat-sheet PDF.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [System Architecture](#2-system-architecture)
3. [Directory Structure](#3-directory-structure)
4. [The 7-Step Pipeline](#4-the-7-step-pipeline)
5. [Algorithms — Deep Dive](#5-algorithms--deep-dive)
   - 5.1 PDF Detection & Table Extraction
   - 5.2 OCR with Tesseract + Fixed Column Splits
   - 5.3 Sentence-BERT Semantic Embeddings
   - 5.4 Centroid-Based Greedy Clustering (Deduplication)
   - 5.5 Recency-Decay Scoring
   - 5.6 Marks Ladder Construction
   - 5.7 Topic Labelling (Ollama / Keyword Fallback)
6. [Data Model (SQLite)](#6-data-model-sqlite)
7. [Module-by-Module Breakdown](#7-module-by-module-breakdown)
8. [Key Dependencies](#8-key-dependencies)
9. [Configuration](#9-configuration)
10. [Research Context](#10-research-context)
11. [How to Run](#11-how-to-run)
12. [Limitations & Known Issues](#12-limitations--known-issues)

---

## 1. Problem Statement

VTU 5th-semester B.E./B.Tech. (CS) exams follow the CBCS (Choice Based Credit System) pattern. Each paper has 5 modules, each worth 20 marks. Questions repeat — sometimes verbatim, sometimes paraphrased — across years and exam sessions (Jan, Jun, Dec, etc.).

**The student's problem:** Out of hundreds of past questions, which ones are most likely to appear and carry the most marks?

**What this app solves:**

- Automatically reads every past paper PDF (whether natively digital or scanned)
- Extracts every individual sub-question with its marks, Bloom's level, and CO number
- Identifies when the "same" question appears across multiple papers (even if phrased differently)
- Scores each topic by how often it repeats AND how recently it appeared
- Presents a ranked list per module so a student can study top-down and "lock in" marks

---

## 2. System Architecture

```
┌───────────────────────────────────────────────────────────┐
│                        Streamlit UI                       │
│  ┌─────────────────┐         ┌────────────────────────┐  │
│  │  pages/1_Upload │         │  pages/2_Dashboard     │  │
│  │  • Upload PDFs  │         │  • Per-subject tabs    │  │
│  │  • Run pipeline │         │  • Module marks ladder │  │
│  │  • Manage DB    │         │  • PDF export          │  │
│  └────────┬────────┘         └────────────────────────┘  │
└───────────┼───────────────────────────────────────────────┘
            │ pipeline.run()
            ▼
┌───────────────────────────────────────────────────────────┐
│                     pipeline.py (orchestrator)            │
│  Step 1: detector.detect_and_extract()                    │
│  Step 2: parser.parse_rows()                              │
│  Step 3: db.insert_paper() + db.insert_sub_questions()    │
│  Step 4: deduplicator.deduplicate()                       │
│  Step 5: scorer.score_canonicals()                        │
│  Step 6: tagger.batch_generate_labels()                   │
│  Step 7: db.upsert_canonical() + db.insert_appearance()   │
└──────────────────────────┬────────────────────────────────┘
                           │
                           ▼
                   ┌───────────────┐
                   │  papers.db    │  ← SQLite
                   │  (SQLite)     │
                   └───────────────┘
```

---

## 3. Directory Structure

```
Papers-Please/
├── app.py                  ← Streamlit entry point (home page)
├── pipeline.py             ← 7-step end-to-end orchestrator
├── requirements.txt        ← Python dependencies
├── config.yaml             ← Configuration reference (thresholds, subject map)
├── _diag.py                ← Debug helper: print extracted rows for a PDF
├── .gitignore
│
├── modules/
│   ├── __init__.py
│   ├── detector.py         ← PDF type detection + table/OCR extraction
│   ├── parser.py           ← Raw table rows → structured sub_question dicts
│   ├── db.py               ← SQLite schema and all CRUD operations
│   ├── embedder.py         ← Sentence-BERT encoding (paraphrase-MiniLM-L6-v2)
│   ├── deduplicator.py     ← Centroid-based greedy clustering
│   ├── scorer.py           ← Recency-decay scoring + marks ladder
│   ├── tagger.py           ← Ollama LLM or keyword topic labels
│   └── exporter.py         ← fpdf2 cheat-sheet PDF generation
│
└── pages/
    ├── 1_Upload.py         ← Upload PDFs, trigger pipeline, manage papers
    └── 2_Dashboard.py      ← Per-subject analysis and PDF download

── (gitignored, created at runtime) ──
data/
├── papers.db               ← SQLite database
├── raw/                    ← Uploaded PDFs
└── extracted/              ← Debug JSON cache of raw extracted rows
```

---

## 4. The 7-Step Pipeline

The entire processing flow lives in `pipeline.run(pdf_paths, db_path)`. Here is what happens end-to-end when you upload one or more PDFs:

```
PDF File(s)
    │
    ▼ Step 1 — detect_and_extract
    │  Is it a native digital PDF?
    │    YES → pdfplumber table extraction
    │    NO  → PyMuPDF render at 300 DPI → Tesseract OCR → fixed column splits
    │
    ▼ Step 2 — parse_rows
    │  Raw rows → structured sub_question records
    │  Each record: {module, q_no, sub_q, text, marks, bloom, co}
    │
    ▼ Step 3 — save_to_db
    │  INSERT into `papers` table
    │  INSERT each sub_question into `sub_questions` table
    │
    ▼ Step 4 — deduplicate (per subject, per module)
    │  Encode all sub_questions with Sentence-BERT
    │  Run centroid-based greedy clustering (threshold = 0.70)
    │  Output: canonical_question groups with appearance lists
    │
    ▼ Step 5 — score_canonicals
    │  For each canonical: weighted_score = Σ 0.85^(currentYear - paperYear)
    │  frequency = distinct paper count
    │  expected_marks = (frequency / total_papers) × avg_marks
    │
    ▼ Step 6 — tag_topics
    │  Ollama LLM (if available) → short topic label
    │  Fallback: top-frequency keywords from question text
    │
    ▼ Step 7 — persist_canonicals
       INSERT/UPDATE `canonical_questions` table
       INSERT each appearance into `appearances` table
```

**Progress reporting:** The pipeline accepts an optional `progress_callback(step: str, pct: float)` so the Streamlit UI can display a live progress bar (steps 1–3 = 0–60%, steps 4–7 = 60–100%).

---

## 5. Algorithms — Deep Dive

### 5.1 PDF Detection & Table Extraction

**File:** `modules/detector.py`

The first challenge is reading the question paper. VTU papers come in two flavours:

| Type | Description | Tool Used |
|------|-------------|-----------|
| **Native** | Digitally created PDF with embedded text layer | `pdfplumber` |
| **Scanned** | Photograph/scan of a physical paper, no text layer | `PyMuPDF` + `Tesseract` |

**Detection logic:**
```
if total_text_chars < 100 OR no table rows extracted:
    → treat as SCANNED
else:
    → treat as NATIVE
```

For **native PDFs**, `pdfplumber` uses its built-in table detection (looks for ruling lines or whitespace columns) and returns each cell as a string. This works cleanly for PDFs typeset with tools like MS Word or LaTeX.

---

### 5.2 OCR with Tesseract + Fixed Column Splits

**File:** `modules/detector.py` → `_extract_scanned()` and `_ocr_page_to_rows()`

For **scanned PDFs**, a more sophisticated pipeline runs:

**Step A — Render to image:**
```python
mat = fitz.Matrix(300/72, 300/72)   # 300 DPI scale matrix
pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)
```
The page is rendered to a grayscale NumPy array at 300 DPI. Higher DPI → Tesseract has more pixels → better accuracy.

**Step B — Tesseract word detection (PSM 6):**
```python
data = pytesseract.image_to_data(pil, output_type=pytesseract.Output.DICT, config="--psm 6")
```
PSM 6 = "Assume a single uniform block of text." This gives word-level bounding boxes (left, top, width, height, confidence, text).

**Step C — Row grouping by vertical centre:**
Words are sorted by their vertical centre (`cy`). Words within 14 pixels of each other vertically are grouped into the same "horizontal band" (a row).

**Step D — Fixed column splits:**
VTU CBCS papers have a consistent 6-column layout. Rather than trying to auto-detect column boundaries (which fails on pages with headers/footers), the code uses fixed proportional splits calibrated from actual papers:

```
| Column     | Horizontal range (% of page width) |
|------------|-------------------------------------|
| Q.No       | 0% – 13%                            |
| Sub        | 13% – 17%                           |
| Question text | 17% – 74%                        |
| Marks (M)  | 74% – 83%                           |
| Bloom (L)  | 83% – 89%                           |
| CO (C)     | 89% – 98%                           |
```

Each word is assigned to a bucket based on where its horizontal centre falls. Buckets are joined into cell strings. This is why the algorithm is robust — it doesn't depend on detecting lines or borders in the image.

---

### 5.3 Sentence-BERT Semantic Embeddings

**File:** `modules/embedder.py`

Model: **`paraphrase-MiniLM-L6-v2`** from the `sentence-transformers` library.

- **Size:** ~90 MB, CPU-only (no GPU required)
- **Output:** 384-dimensional dense vector per text
- **Key property:** Trained specifically on **paraphrase pairs** — meaning "Explain CRC" and "Describe the working of CRC encoder with a diagram" will map to nearby points in the 384-D space

Why this model and not a general one?
- `all-MiniLM-L6-v2` (the default "general" model) is trained on diverse web data — it handles similarity between broad concepts
- `paraphrase-MiniLM-L6-v2` is fine-tuned on paraphrase datasets — it is much better at recognising that `"Explain X"` ≈ `"Describe X in detail"` which is the dominant pattern in exam question repetition

**Normalisation:** All embeddings are L2-normalised (unit vectors). This means:
```
cosine_similarity(a, b) = dot_product(a, b)
```
...which makes similarity computation very fast (just a dot product, no division needed).

**OCR text cleaning before embedding:**
Scanned PDFs produce noisy text (`"AWith X"` instead of `"With X"`, leading pipes, sub-question labels like `"a."`, `"Q.3"`, etc.). The `_clean_for_embed()` function in `deduplicator.py` strips all of this before encoding so the model sees clean academic text.

---

### 5.4 Centroid-Based Greedy Clustering (Deduplication)

**File:** `modules/deduplicator.py`

This is the **core algorithm** of the project. It groups semantically similar questions from different exam years into one "canonical question."

**Why not simple pairwise cosine similarity?**
- With N questions, you'd need N² comparisons — slow for large datasets
- Two questions A and B might not be directly close but both cluster around a centroid C

**The Algorithm (Online / Greedy):**

```
cluster_members   = []   # list of lists: indices of members per cluster
cluster_centroids = []   # one mean embedding per cluster (L2-normalized)

For each new question embedding vec_i:
    best_sim   = -1
    best_clust = -1

    For each existing cluster c:
        sim = dot(vec_i, centroid_c)        # cosine sim (both normalized)
        if sim > best_sim:
            best_sim   = sim
            best_clust = c

    if best_sim >= 0.70:
        # Join the best-matching cluster
        cluster_members[best_clust].append(i)
        # Incremental mean update (Welford's online algorithm):
        n = len(cluster_members[best_clust])
        new_centroid = centroid + (vec_i - centroid) / n
        centroid = new_centroid / ||new_centroid||   # re-normalize
    else:
        # Start a new cluster with this question as seed
        cluster_members.append([i])
        cluster_centroids.append(vec_i)
```

**Threshold = 0.70 (tuned):**
- `>= 0.80` is too strict — misses clear paraphrases like "explain X" vs "describe X with diagram"
- `<= 0.60` is too loose — may merge different topics in the same module

**Representative text selection:**
After clustering, the representative text for a canonical question is chosen from the cluster member that is:
1. From the **most recent year** (most relevant phrasing)
2. Tie-broken by **longest text** (more descriptive)

---

### 5.5 Recency-Decay Scoring

**File:** `modules/scorer.py`

Once questions are grouped into canonicals, each canonical needs a score that reflects both **how often** it appears and **how recently**.

**Formula:**
```
weighted_score = Σ  DECAY ^ (current_year - paper_year)
                 for each unique paper in which the question appeared
```

Where `DECAY = 0.85`. This gives:

| Paper Year | Weight (if current = 2026) |
|------------|---------------------------|
| 2026       | 1.00                      |
| 2025       | 0.85                      |
| 2024       | 0.72                      |
| 2023       | 0.61                      |
| 2022       | 0.52                      |
| 2021       | 0.44                      |

**Why exponential decay?**
- Exam setters tend to change questions over time — a question from 5 years ago is less predictive than one from last year
- Exponential decay is the standard mathematical model for "decreasing relevance with time" (same principle used in stock price momentum, email inbox aging, etc.)

**Additional metrics computed:**
```
frequency       = count of DISTINCT papers the question appeared in
frequency_pct   = frequency / total_papers
expected_marks  = frequency_pct × avg_marks_when_asked
```

`expected_marks` answers the question: "If I study this topic, how many marks can I statistically expect it to be worth?"

---

### 5.6 Marks Ladder Construction

**File:** `modules/scorer.py` → `build_marks_ladder()`

The marks ladder is the final output presented to students. It is built by:

1. Sort all canonical questions by `weighted_score` descending (highest priority first)
2. Walk down the sorted list, accumulating `expected_marks`
3. Track `cumulative_expected` — the running total of expected marks
4. Mark `full_coverage = True` once cumulative hits `max_marks` (20)
5. Stop the ladder once cumulative exceeds `1.5 × max_marks` (30) — enough coverage found

**What it tells a student:**
```
Rank 1 | "Explain CRC encoder" | freq=4/5 papers | expected=6.4M | cumulative=6.4M
Rank 2 | "Hamming code error detection" | freq=3/5 | expected=4.8M | cumulative=11.2M
Rank 3 | "Compare stop-and-wait vs Go-Back-N" | freq=3/5 | expected=4.8M | cumulative=16.0M ✓ full coverage
...
```

By rank 3 in this example, studying just 3 topics statistically covers all 20 marks of the module.

---

### 5.7 Topic Labelling

**File:** `modules/tagger.py`

Each canonical question needs a short human-readable label (e.g., "CRC Error Detection" rather than the full question text).

**Primary method — Ollama LLM:**
If a locally running Ollama server is available (e.g., with `phi3:mini`, `llama3.2`, `mistral`, etc.), the tagger sends the representative text to it with a prompt asking for a 3–5 word topic label.

**Fallback — Keyword frequency:**
If Ollama is unavailable, the tagger tokenises the question texts in the cluster, removes stop-words, and picks the top-3 most frequent content words as the label.

---

## 6. Data Model (SQLite)

**File:** `modules/db.py`

Four tables, related as shown:

```
papers                          sub_questions
──────────────────────────      ─────────────────────────────
id (PK)                    1    id (PK)
filename                   ├──< paper_id (FK → papers.id)
subject_code               │    module_no
subject_name               │    q_no
month                      │    sub_q
year                       │    text
pdf_type                   │    marks
                                bloom_level
                                co_number

canonical_questions             appearances
─────────────────────────  1    ───────────────────────────────
id (PK)                    ├──< canonical_id (FK)
subject_code                    sub_question_id (FK)
module_no                       paper_id (FK)
representative_text             year
topic_label                     q_no
avg_marks                       sub_q
frequency                       marks
weighted_score
last_seen_year
```

**Key constraints:**
- `papers.filename` has a UNIQUE constraint — re-uploading the same file is a no-op unless `force=True`
- `canonical_questions` are deleted and rebuilt from scratch each time a subject is re-analysed (guarantees consistency when new papers are added)
- `appearances` links each canonical to every individual sub_question occurrence across all papers

---

## 7. Module-by-Module Breakdown

### `app.py`
Streamlit home page. Sets page config, title, and a short navigation blurb. Streamlit automatically discovers `pages/` directory.

### `pipeline.py`
The orchestrator. Calls all other modules in order. Handles per-PDF errors gracefully (one bad PDF doesn't abort the rest). Manages the 0–100% progress bar feedback. Separates extraction (steps 1–3) from analysis (steps 4–7).

### `modules/detector.py`
- `detect_and_extract(pdf_path)` — public entry point
- `_extract_native()` — pdfplumber tables
- `_extract_scanned()` → `_page_to_array()` + `_ocr_page_to_rows()` — PyMuPDF + Tesseract
- `parse_filename_metadata()` — regex on filename for BCS code, year, month
- `parse_content_metadata()` — regex on first 15 rows of extracted text for exam line, subject name, BCS code

### `modules/parser.py`
Stateful row scanner. Identifies module headers ("Module 1", "MODULE – 2", etc.), question numbers (Q.1–Q.10 → maps to modules 1–5), sub-question labels (a/b/c), continuation lines (text that flows into the next row), OR rows (skipped — these are alternate question choices). Produces clean sub_question dicts.

### `modules/db.py`
All SQLite operations:
- `init_db()` — CREATE TABLE IF NOT EXISTS for all 4 tables + indexes
- `insert_paper()` / `insert_sub_questions()` — write phase
- `get_sub_questions_for_module()` — read phase for dedup
- `upsert_canonical()` / `insert_appearance()` — write phase for analysis
- `get_canonicals_for_module()` / `get_appearances_for_canonical()` — read phase for dashboard
- `delete_canonicals_for_subject()` — clean slate before re-analysis
- `paper_exists()` — duplicate check

### `modules/embedder.py`
Lazy-loads `paraphrase-MiniLM-L6-v2` once and caches it for the process lifetime. `encode(texts)` returns shape `(N, 384)` float32 L2-normalized array. `cosine_similarity_matrix(a, b)` returns `a @ b.T` (valid because both sides are normalized).

### `modules/deduplicator.py`
OCR text cleaner (`_clean_for_embed`) + centroid-based greedy clustering algorithm (described in Section 5.4). Returns list of canonical dicts with `representative_text`, `avg_marks`, and `appearances`.

### `modules/scorer.py`
`score_canonicals()` — adds `weighted_score`, `frequency`, `frequency_pct`, `expected_marks`, `years`, `last_seen_year` to each canonical. `build_marks_ladder()` — sorts and accumulates into the ranked ladder. `format_years()` and `format_appearances()` — display helpers for the UI.

### `modules/tagger.py`
`batch_generate_labels()` — tries Ollama (detects available models with `ollama list`), falls back to keyword extraction. Labels are attached to canonical dicts as `topic_label`.

### `modules/exporter.py`
Uses `fpdf2` to generate a printable PDF cheat-sheet. Text is sanitised to ASCII-safe characters (OCR sometimes produces Unicode noise). Lays out one section per module with the top questions, expected marks, and appearance years.

### `pages/1_Upload.py`
Streamlit page for:
- PDF file uploader (multi-file)
- Saving uploaded files to `data/raw/`
- Calling `pipeline.run()` with a live progress bar
- Listing all papers currently in the DB (with delete option)
- "Clear all data" button

### `pages/2_Dashboard.py`
Streamlit page for:
- Subject selector dropdown
- Tabs for modules 1–5
- Per-module marks ladder displayed as a table/cards
- "Download Cheat Sheet PDF" button
- Calls `pipeline.get_module_analysis()` to load data

---

## 8. Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `streamlit` | latest | Web UI framework |
| `pdfplumber` | latest | Native PDF table extraction |
| `pymupdf` (`fitz`) | latest | PDF-to-image rendering for scanned PDFs |
| `pytesseract` | latest | Python wrapper for Tesseract OCR |
| `opencv-python` | latest | Image processing (grayscale, pixel ops) |
| `Pillow` | latest | Image format bridge between PyMuPDF and Tesseract |
| `sentence-transformers` | latest | Sentence-BERT embedding model |
| `numpy` | latest | Matrix operations for embeddings + clustering |
| `pandas` | latest | Tabular display in Streamlit |
| `scikit-learn` | latest | Available for future ML features |
| `fpdf2` | latest | Cheat-sheet PDF generation |
| `plotly` | latest | Charts in dashboard |
| `ollama` | latest | Optional local LLM topic labelling |

**System dependency:** Tesseract OCR must be installed and on PATH. On Windows: download from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki).

---

## 9. Configuration

`config.yaml` documents the intended tunable knobs (not yet wired into code — code uses inline constants):

| Parameter | Default | Where in code |
|-----------|---------|---------------|
| DB path | `data/papers.db` | `pipeline.py` callers |
| Extraction DPI | `300` | `detector.DPI` |
| Min native text per page | `100` chars | `detector.MIN_NATIVE_TEXT_PER_PAGE` |
| Dedup threshold | `0.70` | `deduplicator.SIMILARITY_THRESHOLD` |
| Recency decay | `0.85` | `scorer.RECENCY_DECAY` |
| Max module marks | `20` | `scorer.MAX_MODULE_MARKS` |

**Note:** `config.yaml` and `deduplicator.py` currently disagree — YAML says `0.80`, code uses `0.70`. The code value is the operative one.

---

## 10. Research Context

### Problem Domain

This project sits at the intersection of three research areas:

#### A. Information Extraction from Documents
Extracting structured data from semi-structured PDF documents is a well-studied problem in document analysis. VTU papers have a fixed table schema (Q.No | Sub | Text | Marks | Bloom | CO), but real-world papers are noisy — some are digital, some are scanned, some have headers that break column detection.

The project uses a **hybrid extraction strategy** (native tables first, OCR fallback) which is standard practice in production document parsing pipelines.

#### B. Semantic Textual Similarity (STS)
The central research question is: "Are these two exam questions the same?" This is an instance of the **Semantic Textual Similarity** task, widely studied in NLP. The benchmark for STS is the STS-Benchmark (Cer et al., 2017).

The model used — `paraphrase-MiniLM-L6-v2` — is from the **Sentence-BERT** paper (Reimers & Gurevych, 2019). SBERT demonstrated that by fine-tuning BERT with a siamese network architecture on natural language inference (NLI) and paraphrase data, you get sentence embeddings where cosine similarity directly reflects semantic similarity. This was a major improvement over plain BERT which required expensive cross-encoding of sentence pairs.

**MiniLM-L6** is a knowledge-distilled version of BERT — 6 transformer layers instead of 12, with minimal accuracy loss, running 2–5× faster. Suitable for CPU inference which is the target here.

#### C. Clustering for Information Retrieval
The **centroid-based greedy clustering** algorithm used here is a variant of **online k-means / streaming clustering**. It is related to:
- **DBSCAN** (density-based clustering) — but simpler: no ε-neighbourhood, single pass
- **Leader clustering** — each new point either joins the nearest leader (centroid) or becomes a new leader
- **Welford's online algorithm** — for computing running mean without storing all past values

The advantage over offline clustering (k-means, hierarchical) is:
1. O(N × C) time where C = number of clusters (much less than N²)
2. No need to pre-specify the number of clusters k
3. Can process questions in streaming fashion

The **recency-decay scoring** is an instance of **temporal weighting** used in many recommendation and information retrieval systems (e.g., news feed ranking, PageRank variants, financial time series).

### What Makes This Novel (for the specific domain)

1. **VTU-specific layout knowledge** baked into the column split constants — this is domain adaptation
2. **OCR noise cleaning before embedding** — important because generic NLP models perform poorly on OCR artifacts like "AExplain" or "Q.3a Describe"
3. **Threshold tuning for academic paraphrases** — 0.70 instead of the typical 0.80 used for general STS, because exam question paraphrases are looser ("Explain X" vs "Describe X with a neat diagram")
4. **Expected marks as a decision variable** — framing study prioritisation as an expected value problem under uncertainty (which topics to study to maximise expected exam marks)

---

## 11. How to Run

### Prerequisites

1. Python 3.11+
2. Tesseract OCR installed
   - Windows: download from [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki), add to PATH
   - Linux: `sudo apt install tesseract-ocr`
3. (Optional) [Ollama](https://ollama.com) running locally with at least one model (`phi3:mini` recommended)

### Installation

```bash
# From the project root
pip install -r requirements.txt
```

On first run, `sentence-transformers` will download the `paraphrase-MiniLM-L6-v2` model (~90 MB).

### Running the App

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

### Workflow

1. Go to **Upload** page → upload past paper PDFs (name them like `JAN 2025 BCS502.pdf`)
2. Click **Process Papers** — watch the progress bar
3. Go to **Dashboard** page → select your subject → browse module tabs
4. Click **Download Cheat Sheet PDF** for a printable version

### CLI / Scripting

```python
from pipeline import run

summary = run(
    pdf_paths=["data/raw/JAN 2025 BCS502.pdf", "data/raw/DEC 2024 BCS502.pdf"],
    db_path="data/papers.db",
    force=False,
)
print(summary)
```

---

## 12. Limitations & Known Issues

| Issue | Impact | Notes |
|-------|--------|-------|
| `config.yaml` not loaded | Low | Code uses hardcoded constants. YAML is reference only. |
| Threshold mismatch | Low | YAML says 0.80, code uses 0.70 |
| Tagger reads wrong field | Low | `tagger.py` looks for `text` on appearance dicts; falls back gracefully to keyword method |
| Single-paper subjects | Low | When only 1 paper is uploaded, frequency-based ranking is meaningless — code falls back to ranking by marks |
| Greedy clustering is order-dependent | Medium | Cluster assignments can differ based on the order questions are processed. A post-processing step (iterative refinement) could improve stability. |
| No cross-module similarity | Medium | Questions very similar across modules are treated as separate — by design, since VTU assigns topics to specific modules |
| Tesseract accuracy on very low-quality scans | High | Heavily degraded scans (coffee stains, heavy shadows, rotation) will produce poor OCR, which downstream cleaning only partially fixes |
| Only BCS5xx subjects supported | Medium | Subject code detection is limited to the VTU_SUBJECT_MAP in `detector.py`. Adding other semesters requires extending this map. |
| scikit-learn imported but unused | Low | Listed in requirements.txt, available for future clustering enhancements |

---

*Documentation generated: April 2026*
