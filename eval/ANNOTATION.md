# Ground-truth annotation guide

Ground truth lives in `data/eval/ground_truth/` (gitignored, like the papers themselves).
Two kinds of file:

## 1. Paper transcriptions — `data/eval/ground_truth/papers/<paper_id>.json`

Transcribe **what is printed on the paper**, read from the page images in
`data/eval/pages/<paper_id>/`. Never look at the system's extracted output
while transcribing.

```json
{
  "paper_id": "july_2025_BCS502",
  "file": "july 2025 BCS502.pdf",
  "subject_code": "BCS502",
  "subject_name": "Computer Networks",
  "paper_type": "see",            // "see" = semester-end exam, "model" = model question paper
  "exam_month": "July",           // as printed; null for model papers without a session
  "exam_year": 2025,
  "notes": "anything odd: pages missing, illegible parts, handwriting",
  "questions": [
    {"module": 1, "q_no": 1, "sub_q": "a", "marks": 10,
     "text": "Define Data Communications. Explain the characteristics and components of Data communication with neat diagram."}
  ]
}
```

Rules:
- One entry per printed **sub-question** (a, b, c…). If a question has no sub-parts, use `"sub_q": "a"`.
- Numbered items *inside* a sub-question (i, ii, iii) stay inside that sub-question's text. They are not separate entries.
- `module` is the "Module – N" block the question sits in. `q_no` is the printed question number (1–10).
- `marks` is the printed M column (integer), or `null` if it isn't printed or can't be read.
- `text` is the full question text, corrected to what is actually printed (fix line breaks, but keep the wording). Leave out the L/CO columns.
- Mark anything you can't read as `[illegible]` in the text and mention it in `notes`.

## 2. Equivalence groups — `data/eval/ground_truth/groups/<subject_code>.json`

For each subject, group sub-questions from **all its papers** that ask **the same thing**.

The test: *if a student fully prepared an answer to one, could they answer the other
without further study?* If yes, they're in the same group.
- Same concept and same expected answer, in different words → **same group**
  ("Explain CRC with example" / "Describe the CRC encoder and decoder").
- Same broad topic but different things asked → **different groups**
  ("Explain TCP connection establishment" vs "Explain TCP congestion control").
- One question that asks for A and B together, and another that asks for A only →
  same group if A is clearly the main body of both, otherwise different.
- Groups never cross modules or subjects.

```json
{
  "subject_code": "BCS502",
  "groups": [
    {"label": "Data communication: characteristics and components",
     "members": ["july_2025_BCS502:Q1a", "JAN_2025_BCS502:Q1a", "BCS502_MQP_1:Q1c"]}
  ],
  "borderline": [
    {"members": ["…:Q3b", "…:Q4a"], "why": "related but not the same expected answer"}
  ]
}
```

Every sub-question of every paper in the subject must appear in exactly one group;
singletons are groups of one. Each member reference is `<paper_id>:Q<q_no><sub_q>`.
