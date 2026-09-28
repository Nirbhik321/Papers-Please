import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "How ranking works",
  description: "How Papers Please groups reworded VTU questions, ranks topics by how often they repeat, and keeps uploads safe.",
};

const STEPS = [
  {
    title: "Read every paper",
    body: "Digital PDFs are read directly. Scanned ones go through OCR, and the VTU table layout (question number, sub-question, marks, Bloom level, CO) is rebuilt row by row.",
  },
  {
    title: "Group reworded questions",
    body: "“Explain CRC” and “Describe the CRC encoder with a neat diagram” are the same question. A sentence-embedding model trained on paraphrases compares every question in a module, across all papers, and groups the ones that mean the same thing. Where a question sat in the paper (Q3a or Q4b) doesn't matter.",
  },
  {
    title: "Rank by repetition, weighted to recent papers",
    body: "A topic scores one point for every paper it appeared in, with older papers counting a little less (each year back is worth 85% of the year after). Topics in every paper rise to the top.",
  },
  {
    title: "Turn it into marks",
    body: "Expected marks = the share of papers a topic appeared in × its usual marks. Adding these down the ranking gives the marks ladder: “study the top 3 topics to cover the module”.",
  },
];

export default function HowItWorks() {
  return (
    <main className="mx-auto flex max-w-[1440px] gap-16 px-20 pt-16 pb-8">
      <div className="flex max-w-[760px] flex-col gap-10">
        <div className="flex flex-col gap-4">
          <p className="font-mono text-[13px] tracking-[0.08em] text-stamp">HOW RANKING WORKS</p>
          <h1 className="font-display text-[56px] leading-[1.05] font-semibold">From a pile of papers to what to study first</h1>
          <p className="text-lg leading-relaxed text-ink-2">
            VTU questions repeat — sometimes word for word, often reworded. Papers Please finds those repeats across
            every paper we have for a subject and ranks them, so your revision time goes where the marks are.
          </p>
        </div>
        <ol className="flex flex-col gap-7">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-5">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-[1.5px] border-ink font-mono">{i + 1}</span>
              <div className="flex flex-col gap-1.5">
                <h2 className="font-display text-2xl font-semibold">{s.title}</h2>
                <p className="text-[16px] leading-relaxed text-ink-2">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="rounded-xl border border-line bg-surface px-5 py-4 text-[15px] leading-relaxed text-ink-2">
          <strong className="text-ink">A ranking is not a promise.</strong> It tells you what has come up most often.
          Examiners can and do set new questions, so use it to decide what to study first — not what to skip entirely.
        </p>
      </div>

      <aside className="flex w-[400px] shrink-0 flex-col gap-5 self-start rounded-2xl border border-line bg-surface p-7">
        <h2 className="font-display text-2xl font-semibold">Keeping the data honest</h2>
        <ul className="flex flex-col gap-4 text-[15px] leading-relaxed text-ink-2">
          <li><strong className="text-ink">One paper per exam.</strong> Each subject can only have one live paper per exam session, so a re-scan or re-upload is never counted twice.</li>
          <li><strong className="text-ink">Checked before it counts.</strong> Uploads are read in an isolated sandbox. Files that aren&apos;t question papers are refused, and anything unusual waits for a moderator.</li>
          <li><strong className="text-ink">Originals stay private.</strong> Uploaded PDFs are never shown to anyone — only the extracted questions and the cheat sheets we generate.</li>
        </ul>
        <Link href="/upload" className="mt-2 flex h-12 items-center justify-center rounded-xl bg-ink text-[15px] font-semibold text-inverse hover:opacity-90">
          Upload a paper
        </Link>
      </aside>
    </main>
  );
}
