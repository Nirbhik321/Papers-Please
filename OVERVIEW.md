# Papers Please — Complete Overview

Built by **Prabhat Anil Bajpai** and **Nirbhik Chaki**
CMR Institute of Technology, Bengaluru
GitHub: https://github.com/Nirbhik321/Papers-Please

---

## What This Is

Papers Please is a tool that takes VTU question paper PDFs, processes them end to end, and tells you exactly what to study. Not based on opinions or guesswork. Based on patterns in the actual papers that have been set over the years.

You upload past papers. The system reads them, groups questions that are asking the same thing across different years, scores each group by how often it appeared and how recently, and gives you a ranked list per module. The most repeated, highest-marks topics come first. You study those first and you have already covered most of what the exam is likely to test.

The same output that helps students study also helps teachers. The question bank CSV export contains every grouped question with marks, frequency, and topic label. A teacher can take that file and set an internal assessment paper in minutes instead of hours.

---

## The Problem We Were Solving

Every VTU student does the same thing before exams. You have 4 or 5 past papers per subject, sometimes more. You open each one and try to remember whether you have seen this question before. You make notes. You try to figure out which modules matter most and which topics keep showing up. You do this for every subject, every semester, entirely by hand.

There is no systematic way to do it. You are doing pattern recognition manually on 150 to 200 questions per subject, across multiple PDFs, under time pressure. Most of the time you either try to cover everything and burn out, or you take a guess based on what someone told you was important.

The result is that students waste hours on topics that have never been asked and will probably never be asked, while missing the ones that show up consistently every single year.

Model Question Papers make this worse in a specific way. VTU releases MQPs that are deliberately constructed to cover the entire syllabus systematically. They are the most signal-rich source available. Most students either ignore them entirely or treat them the same as a regular paper, which means they are leaving the best data on the table.

Teachers have their own version of the same problem. Setting an internal assessment paper means going through old papers manually, picking questions that feel balanced across modules and marks, and doing it again from scratch every semester. There is no structured question bank. Just PDFs.

Papers Please was built to fix this. Make the data work for the student instead of against them.

---

## How the System Works

### Step 1: Upload and Extract

A PDF is uploaded through the web interface. The first thing the system does is figure out what kind of PDF it is.

Some PDFs have actual text embedded in them, called native PDFs. These come from digital sources and the text can be read directly. Others are scanned images of physical paper, meaning there is no text layer at all, just a photo.

For native PDFs, a library called pdfplumber reads the table structure directly and returns rows of text. For scanned PDFs, PyMuPDF renders each page as a high-resolution grayscale image at 300 DPI. Before that image goes to Tesseract OCR, it goes through a preprocessing step. Autocontrast stretches the histogram so shadowed or washed-out areas become readable. A sharpening filter improves edge clarity so character boundaries are crisper. A median filter removes the salt-and-pepper noise that shows up on old xerox copies without blurring the text strokes. This preprocessing step was added specifically because raw scans from phone cameras or low-quality scanners were producing garbage OCR output that made the rest of the pipeline useless.

### Step 2: Parse and Structure

VTU question papers follow a consistent 6-column table format: question number, sub-question label (a, b, c), question text, marks, Bloom's taxonomy level, and course outcome. The extracted rows are mapped to this structure.

Module headers are detected using strict regex patterns for the standard case and two fuzzy fallback patterns for garbled OCR where the word Module comes out as something unreadable. Once a module header is found, all questions after it are assigned to that module number until the next header appears. If a module header is missing, the question number is used to infer the module, since VTU always assigns Q1-Q2 to Module 1, Q3-Q4 to Module 2, and so on.

Metadata is extracted from two sources. The filename is checked first for a subject code, year, and month. The subject code regex was updated to cover all VTU 2022 scheme branch prefixes, not just BCS but also BAI, BIS, BEE, BAD, BEC, and every other branch in the scheme. If the filename does not have enough information, the system reads the opening rows of the PDF content and looks for the standard VTU exam header that appears on every paper. It also checks both sources for keywords like MQP, model question paper, or model paper and tags the file accordingly.

### Step 3: Store in Database

The paper metadata and all extracted questions are written to a local SQLite database. SQLite was chosen because it requires zero setup, produces a single file you can move around, and handles the data volumes involved (hundreds of questions across dozens of papers) without any performance issues.

The database has four tables. The papers table stores one row per uploaded PDF with its subject code, year, month, exam type, and pdf type. The sub_questions table stores every individual question extracted from every paper, linked back to the paper it came from. The canonical_questions table stores the deduplicated representative questions after clustering. The appearances table links canonical questions back to the specific sub-questions they represent across papers.

### Step 4: Deduplicate and Group

This is the core of the system. Once all papers for a subject are in the database, every sub-question is loaded into memory. The challenge is that the same question appears across years worded differently. One paper says "Explain the three-way handshake in TCP" and another says "With a neat diagram, describe TCP connection establishment and termination." These are the same question but a simple text comparison would treat them as two separate questions.

The solution is semantic embeddings. Sentence-BERT converts each question into a 384-dimensional vector that represents the meaning of the question, not just its keywords. Questions that mean the same thing end up close together in this vector space even if the wording is completely different.

A 2-pass centroid-based greedy clustering algorithm groups these vectors. In the first pass, questions are processed in order and assigned to the nearest existing cluster if one is close enough, otherwise a new cluster is created. After the first pass, the centroid of each cluster is recalculated as the average of all its members. In the second pass, every question is reassigned to whichever cluster centroid it is now closest to. This second pass removes the order-dependence that makes single-pass clustering unstable, where questions processed early have an outsized influence on which clusters form.

Each cluster gets a canonical representative question, selected as the one closest to the cluster centroid, meaning the clearest average phrasing of all the variations.

### Step 5: Score and Rank

Each canonical question cluster is scored using three signals.

Frequency is the raw count of how many papers it appeared in divided by the total papers for that subject. A question appearing in 4 out of 5 papers has a frequency of 80 percent.

Recency applies exponential decay to the years. A question from last year counts more than one from five years ago. This reflects the fact that question paper setters tend to follow patterns set in recent sessions more than older ones.

Average marks is the mean marks value assigned to that question across its appearances. A 10-mark question carries more weight than a 5-mark one.

These three signals are combined into a weighted score. The clusters for each module are sorted by this score. Then a marks ladder is built. The ladder shows cumulative expected marks as you study topics in ranked order. It answers the question: if I study the top N topics in Module 2, how many marks should I expect to cover? The ladder tells you the point where studying more topics stops adding significant expected marks, which is the coverage threshold.

### Step 6: Generate Topic Labels

Each cluster needs a short human-readable label so the output is actually usable. Seeing "Explain the three-way handshake in TCP" as a cluster representative is fine but having a label like "TCP Three-Way Handshake" makes the dashboard scannable.

The system calls Ollama, a locally running LLM (llama3.2), via its HTTP REST API directly. Using the REST API directly instead of the Ollama Python package was necessary because the Python package requires pydantic version 2 and the environment has pydantic version 1 installed. Calling the API directly over HTTP bypasses that dependency entirely.

The prompt sent to Ollama gives it the top three phrasings of the question and asks for a 3 to 5 word topic label that names the concept without starting with a question verb like explain or define.

If Ollama is not running, a keyword-based fallback is used. It extracts unigrams and bigrams from the question texts, gives bigrams double the weight of single words, preserves acronyms in uppercase (so CRC stays CRC and does not become Crc), and returns the top meaningful phrase.

### Step 7: Output

The processed results go to four places.

The Dashboard is the main web interface. It shows one card per subject with module tabs inside. Each tab lists the ranked questions with frequency bars, average marks, years seen, and the full question text. Papers detected as Model Question Papers get a badge and an info box explaining they carry full weight. A single-paper mode activates automatically when only one paper has been uploaded, showing topic structure and marks breakdown instead of repeat patterns.

The Cheat Sheet PDF is a one-click printable export per subject. It contains the top questions per module, their marks weight, and the years they appeared. It is designed to be the last document a student reads before entering the exam.

The Question Bank CSV is a structured export of every canonical question with module number, average marks, frequency, topic label, and representative text. A teacher can open this in a spreadsheet, filter by module, and have a complete question bank ready to work from. Students can use the same file to build their own study sheet.

The Graph is an interactive force-directed visualization built with D3.js. Nodes represent canonical questions, sized by frequency so the most repeated questions are visually largest and colored by module. Topic clusters are drawn with convex hull shapes grouping related questions. A frequency filter slider at the top lets you hide everything below a threshold so you only see the questions that actually repeat. A Study Path mode highlights the minimum set of topics per module needed to achieve full marks coverage, shown as gold dashed rings on the relevant nodes. Below the graph, a per-module coverage table shows exactly how many topics to study per module and what expected marks that covers.

---

## The Data Behind the System

### subjects.yaml

The system maintains a YAML configuration file with 145+ subject codes covering every subject in the VTU 2022 scheme across all computer stream branches: CSE, ISE, AIML, AIDS, DS, from semester 1 through semester 6. When the system extracts a subject code from a filename or PDF content, it looks this code up to get the full subject name. If the code is not in the file, the code itself is used as the name.

Adding a new subject is a single line in this file.

### The Database

The SQLite database has four tables:

papers stores one row per PDF with columns for filename, subject code, subject name, month, year, pdf type (native or scanned), exam type (regular or mqp), and upload timestamp.

sub_questions stores every individual question with its module number, question number, sub-question label, text, marks, Bloom level, course outcome, and a link to the paper it came from.

canonical_questions stores the deduplicated representative questions with their topic label, average marks, frequency, weighted score, and last seen year.

appearances links each canonical question back to the specific sub-questions across papers that were grouped into it, preserving the full provenance chain from canonical question back to the original paper.

---

## Tech Stack and Why

**pdfplumber** was chosen for native PDF extraction because it handles table structures well and returns clean row data without needing manual boundary detection.

**PyMuPDF** was chosen for rendering scanned pages because it is significantly faster than alternatives and produces clean high-resolution output at any DPI.

**Tesseract OCR** is the standard open-source OCR engine. The preprocessing added before Tesseract (autocontrast, sharpen, median filter) was built using Pillow which is already a dependency, so no new package was needed.

**Sentence-BERT** (paraphrase-MiniLM-L6-v2) produces 384-dimensional semantic embeddings that capture meaning well for short question texts. It runs fully locally, no API key needed, and the model is small enough to load in a few seconds on a laptop.

**SQLite** was chosen over a full database server because the tool is local, the data volumes are modest, and zero setup means anyone can run it by just installing Python dependencies.

**Streamlit** was chosen for the UI because it lets you build a working web interface entirely in Python without writing any HTML or JavaScript for the layout. The graph visualization required D3.js specifically because force-directed graph layouts are not available in Streamlit's native components.

**Ollama** was chosen for LLM labels because it runs completely locally, has no API costs, and works offline. The direct REST API approach means no Python package version conflicts.

---

## What We Learned Building This

The biggest lesson was that the extraction and parsing steps are where most of the real work is. The machine learning parts, the embedding and clustering, mostly just work once you give them clean input. The hard part is getting clean input out of PDFs that were created by scanning a physical paper on a phone camera in a hostel room.

OCR is much more sensitive to preprocessing than expected. The same Tesseract configuration on the same image produces significantly different output depending on whether you stretch the contrast first. The preprocessing step went through several iterations before the output became usable.

The 2-pass clustering was added after noticing that the first-pass results were order-dependent. Questions processed earlier formed cluster centroids that were sometimes not the best centers, and later questions that should have joined those clusters ended up creating new ones instead. The reassignment pass fixed this substantially.

The decision to call the Ollama REST API directly instead of using the Python package was made after discovering that the package required a newer version of pydantic than what was installed. Rather than risk breaking other dependencies by upgrading, the direct HTTP approach turned out to be simpler and more transparent anyway.

---

## Current State

Phase 1 is complete. The full pipeline works end to end on real VTU 2022 scheme papers. It was tested on Computer Networks (BCS502) with 3 regular papers and 1 Model Question Paper. All 4 papers processed without errors. Questions were correctly grouped across papers, module coverage was detected accurately, topic labels were generated by Ollama, and both the CSV and PDF exports worked correctly.

Known limitations at this stage:

Heavily shadowed or blurry scans still produce some noisy OCR output despite preprocessing. The preprocessing helps significantly but cannot fully recover text from a very bad scan.

Files with no subject code anywhere in the filename or PDF content are rejected because there is no reliable way to determine which subject they belong to.

Ollama needs to be running locally for LLM-generated labels. If it is not running, the keyword fallback is used, which produces reasonable labels but not as clean as Ollama's output.

The clustering has no confidence score so there is no way to flag clusters that are weakly grouped. A cluster with three questions that are only loosely similar looks the same in the output as a tight cluster of closely related questions.

The system is local only right now. Two people cannot share a database, and papers uploaded on one machine are not visible to anyone else.

---

## Where This Goes Next

Phase 1 proved the concept works. Phase 2 onwards is about taking it to actual scale.

**Phase 2: Cloud Database.** Migrate from local SQLite to Supabase. During the 4th year, upload as many papers as possible to seed the database properly. The goal is to cover every subject across every computer branch (CSE, ISE, AIML, AIDS, DS) for every semester in the VTU 2022 scheme. That seeded database becomes the foundation everything else is built on.

**Phase 3: Public Website.** Build a website where any VTU student can open a browser, select their subject and semester, and immediately see the ranked question list. No installation. No account. No downloads. Just open and study. The analysis has already been done server-side. They are just reading the output.

**Phase 4: Community Uploads.** Let students upload papers they have collected that are not in the system yet. The system checks for duplicates before accepting anything so the same paper does not get counted twice. Every genuine new upload improves the analysis for every other student using the platform.

**Phase 5: Open Source.** Full public release. Any student from any university with a similar examination structure can fork the repository, point it at their own papers, configure the subject map for their university, and run their own version. The pipeline is not VTU-specific. The subject configuration is a single YAML file. Anyone could adapt this over a weekend.

The end goal is a platform where exam preparation stops being something every student reinvents alone every semester and becomes something the community builds together over time.

---

*Papers Please — Phase 1 complete. Built at CMR Institute of Technology, Bengaluru.*
