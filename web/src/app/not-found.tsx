import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex max-w-[1440px] flex-col items-start gap-5 px-20 pt-24">
      <span className="-rotate-3 rounded-md border-2 border-stamp px-3 py-1 font-mono text-stamp">NOT FOUND</span>
      <h1 className="font-display text-5xl font-semibold">Nothing on this page yet.</h1>
      <p className="max-w-[620px] text-lg text-ink-2">
        If you were looking for a subject, nobody has uploaded a paper for it yet — you could be the first.
      </p>
      <div className="flex gap-3">
        <Link href="/" className="flex h-12 items-center rounded-xl border border-line bg-surface px-5 font-medium">Browse subjects</Link>
        <Link href="/upload" className="flex h-12 items-center rounded-xl bg-ink px-5 font-semibold text-inverse">Upload a paper</Link>
      </div>
    </main>
  );
}
