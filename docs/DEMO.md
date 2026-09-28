# Demo runbook

Everything runs on this laptop: no internet, no accounts, no deployed services needed.
The demo uses its own database in `data/demo/`, so rehearsing never touches your dev data.

---

## Tonight (once, ~5 minutes)

1. Close anything using ports **3000** or **8000** (old dev servers).
2. From the project folder:

   ```powershell
   .venv\Scripts\python scripts\demo.py prepare
   ```

   This seeds the demo database from `data/raw` (every paper goes through the real checks), confirms the papers whose subject couldn't be read, builds the website in production mode, and saves a snapshot.
3. Rehearse the whole flow below once.
4. Reset to a clean state:

   ```powershell
   .venv\Scripts\python scripts\demo.py reset
   ```

## Right before the demo

```powershell
.venv\Scripts\python scripts\demo.py start
```

Wait for the box that says **Papers Please demo is running**, then open these tabs:

| Tab | URL |
|---|---|
| 1 | http://localhost:3000 |
| 2 | http://localhost:3000/s/BCS502 |
| 3 | http://localhost:3000/upload |
| 4 | http://localhost:3000/admin (sign in with the token printed in the box — `papers-please-demo` by default) |

Keep **File Explorer** open at `data\demo\live-upload\`, which holds the four files you'll drag in.

Tips: set the browser zoom so the whole subject page fits the projector (80–90%). Pick light or dark mode with the moon/sun button and stick with it.

---

## The demo (about 8 minutes)

### 1. The problem (30 s)
VTU questions repeat, sometimes word for word, often reworded. Students go through a pile of past papers by hand to find the repeats. We do it automatically, for everyone, from one shared bank.

### 2. Home page (45 s) — tab 1
- Press **/** and type `networks`: results filter instantly, with no server round trip.
- Point out the branch/semester filters and the **Just added** feed. That feed shows papers arriving live, and anyone can add one.
- Type a subject nobody has uploaded yet (e.g. `operating`) to show the "Not in the bank yet — upload a paper" suggestion.

### 3. A subject (2 min) — tab 2, BCS502 Computer Networks
- **Module tabs** and the topic cards: *Very likely / Likely / Occasional*, "In 3 of 3 papers", usual marks.
- The **Appeared in** strip: which exam sessions each topic came up in.
- Click **See all wordings**. **This is the NLP:** differently-worded questions from different papers and positions (Q1a in one paper, Q2b in another) grouped as one topic by a sentence-embedding model trained on paraphrases.
- Tick **Mark studied** on the top 2–3 topics. The **coverage meter** and **marks ladder** fill: "study the top 3 to cover the module". It's saved in the browser, so no account is needed.
- Switch to **Graph**: topics as dots, bigger means more repeats, coloured by module. Hover one, then click it to jump back to it in the list.
- Click **Download cheat sheet**. It's a one-page A4 PDF, generated in advance so it downloads instantly. Mention the CSV question bank for teachers.

### 4. Live upload (1½ min) — tab 3
- Drag **`july 2025 BCS502.pdf`** in. Watch the steps: *Uploaded → Read safely → Confirm details*.
  - While it reads (a scanned paper takes a little while), explain that the PDF is opened in a separate, locked-down process with time limits and no access to secrets. A malicious file can't touch the server.
- The confirm card shows what was detected: BCS502, July 2025, and sample questions. Click **Looks right — submit**, then watch *Matched → Live*.
- Go back to **tab 2** and refresh: BCS502 now says **4 papers**, and the rankings and ladder have updated.

### 5. It can't be gamed (1½ min) — still tab 3
- Drag **`lab-notes.pdf`** in: rejected, "doesn't look like a VTU question paper".
- Drag **`locked.pdf`** in: rejected, password-protected.
- Drag the same file you uploaded in step 4 in again: "This exact file is already in the bank" (SHA-256 match, even if you rename it).
- Drag **`DecJan_2025_-_Scheme  CN-1-2.pdf`** in and confirm it: it goes to **In review**. It's a different scan of the January 2025 exam, and each exam session can only have one live paper, so nothing gets counted twice.

### 6. Moderation (1 min) — tab 4
- **Needs review** shows that upload with the reason.
- Click it: the **side-by-side comparison** matches the new paper's questions against the live paper's, with similarity scores.
- Click **Reject** (or **Replace live copy** if this scan is clearer). Point out the other controls: block uploader, fix the detected subject/session, reprocess.

### 7. How it's built (1 min)
- **Next.js** website: pages are pre-built and refresh the moment a subject changes. Everything interactive happens in the browser.
- **FastAPI** server + our Python pipeline: pdfplumber / Tesseract OCR → parser → **Sentence-BERT on ONNX** → two-pass centroid clustering → recency-weighted scoring → phrase-based topic labels → cheat sheet.
- Heavy work runs on one background worker. Reads are precomputed snapshots, so browsing never waits on it.
- Production setup on free tiers: **Vercel + Render + Supabase** (Postgres with row-level security, private storage, moderator login). A cron job keeps the free server awake.

---

## Likely questions

| Question | Answer |
|---|---|
| How do you know two questions are the same? | Every question is turned into a 384-number vector by `paraphrase-MiniLM-L6-v2`, a model trained on paraphrase pairs. Questions in the same module whose vectors are ≥ 0.70 similar (cosine) are grouped. A second pass reassigns everything against fresh group centres, so the order papers were added doesn't matter. |
| Why not k-means? | You'd have to know the number of topics in advance, and DBSCAN's settings don't carry over between modules of different sizes. Centroid clustering needs one threshold. |
| How is the ranking computed? | Each paper a topic appears in adds 0.85^(years ago), so recent papers count more. Expected marks = share of papers it appeared in × its usual marks. The ladder adds those up until the module's 20 marks are covered. |
| What stops fake uploads? | A human check (Turnstile) and rate limits online; file checks; a sandbox; duplicate detection by hash, by exam session and by question overlap; structural checks; and a moderator queue for anything unusual. Original PDFs are never shown to anyone. |
| Does it work on scanned papers? | Yes. Pages are rendered at 300 DPI, cleaned up (contrast and sharpening), OCR'd with Tesseract, and rebuilt into VTU's table columns. The parser tolerates OCR errors like "O22" for Q.2 and "BCSS02" for BCS502. |
| Is it a guarantee? | No. It shows what has come up most often, so students know what to study first, not what to skip. |
| What does it cost to run? | Nothing: free tiers of Vercel, Render and Supabase. The model runs on ONNX instead of PyTorch so it fits in a 512 MB server. |

---

## If something goes wrong

| Problem | Fix |
|---|---|
| `start` says a port is in use | Close the old server window (or restart the laptop), then run `start` again. |
| An upload sits on "Read safely" for more than 2 minutes | Check the `start` window for errors. It's usually a very large scan. Carry on with the next file. |
| A page shows old data | Refresh once. `start` refreshes every page at launch. |
| You rehearsed and want a clean slate | Ctrl+C, then `demo.py reset`, then `demo.py start`. |
| Everything is broken | `demo.py prepare` again (about 5 minutes). |
