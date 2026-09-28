import Link from "next/link";
import { getCatalog, getRecent, getStats, getSubjects } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { SubjectBrowser } from "./SubjectBrowser";

export const revalidate = 300;

export default async function Home() {
  const [subjects, catalog, stats, recent] = await Promise.all([
    getSubjects(), getCatalog(), getStats(), getRecent(),
  ]);

  const justAdded = (
    <aside className="w-[440px] shrink-0 rounded-2xl border border-line bg-surface p-7">
      <div className="mb-2.5 flex items-baseline justify-between">
        <h2 className="font-display text-[22px] font-semibold">Just added</h2>
        <span className="text-[13px] text-ink-2">Live from uploads</span>
      </div>
      {recent.length === 0 ? (
        <p className="border-t border-line-soft py-4 text-[15px] text-ink-2">
          Nothing yet — the first papers are on their way.
        </p>
      ) : (
        <ul>
          {recent.map((r, i) => (
            <li key={`${r.code}-${r.label}-${i}`}>
              <Link href={`/s/${r.code}`} className="flex items-center gap-3.5 border-t border-line-soft py-3.5 text-ink">
                <span className="w-[74px] font-mono text-[13px] text-stamp">{r.code}</span>
                <span className="flex flex-grow flex-col gap-0.5">
                  <span className="text-[15px] font-medium">{r.name}</span>
                  <span className="text-[13px] text-ink-2">{r.label.startsWith("Model") ? r.label : `${r.label} paper`} added</span>
                </span>
                <span className="text-[13px] text-ink-2">{formatDate(r.addedAt)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 border-t border-line-soft pt-3.5 font-mono text-[13px] text-ink-2">
        {stats.papers} papers · {stats.subjects} subjects in the bank
      </p>
    </aside>
  );

  return (
    <main>
      <SubjectBrowser subjects={subjects} catalog={catalog} aside={justAdded} />

      <section className="mx-auto mt-4 max-w-[1440px] px-20">
        <div className="flex items-center gap-8 rounded-[18px] bg-ink px-11 py-9 text-inverse">
          <div className="flex flex-grow flex-col gap-2">
            <h2 className="font-display text-3xl font-semibold">Got a paper we&apos;re missing?</h2>
            <p className="text-base opacity-80">
              Upload it — it takes about a minute. Every new paper sharpens the ranking for everyone taking that subject.
            </p>
          </div>
          <Link href="/upload"
            className="flex h-[52px] items-center rounded-xl bg-paper px-6 text-base font-semibold text-ink hover:opacity-90">
            Upload a paper
          </Link>
        </div>
      </section>
    </main>
  );
}
