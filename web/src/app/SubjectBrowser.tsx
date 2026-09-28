"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { SearchIcon } from "@/components/Icons";
import { plural, yearRange } from "@/lib/format";
import type { CatalogEntry, SubjectSummary } from "@/lib/types";

type Sort = "papers" | "recent" | "code";

function matches(query: string, code: string, name: string) {
  const hay = `${code} ${name}`.toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

function Chip({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={`h-[38px] min-w-11 cursor-pointer rounded-full border px-4 text-sm font-medium ${
        on ? "border-ink bg-ink text-inverse" : "border-line bg-surface text-ink hover:border-line-strong"}`}>
      {label}
    </button>
  );
}

export function SubjectBrowser({ subjects, catalog, aside }: {
  subjects: SubjectSummary[];
  catalog: CatalogEntry[];
  aside: React.ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [branch, setBranch] = useState<string | null>(null);
  const [semester, setSemester] = useState<number | null>(null);
  const [sort, setSort] = useState<Sort>("papers");
  const searchRef = useRef<HTMLInputElement>(null);

  // "/" jumps to search, like most sites students already use
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const branches = useMemo(() => {
    const counts = new Map<string, number>();
    subjects.forEach((s) => counts.set(s.branch, (counts.get(s.branch) || 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([b]) => b);
  }, [subjects]);
  const semesters = useMemo(
    () => [...new Set(subjects.map((s) => s.semester).filter((n): n is number => !!n))].sort(),
    [subjects],
  );

  const shown = useMemo(() => {
    const list = subjects.filter((s) =>
      (!query || matches(query, s.code, s.name)) &&
      (!branch || s.branch === branch) &&
      (!semester || s.semester === semester));
    return list.sort((a, b) =>
      sort === "code" ? a.code.localeCompare(b.code)
        : sort === "recent" ? (b.updatedAt || "").localeCompare(a.updatedAt || "")
          : b.paperCount - a.paperCount || a.code.localeCompare(b.code));
  }, [subjects, query, branch, semester, sort]);

  // Subjects the search matches that nobody has uploaded yet
  const missing = useMemo(() => {
    if (query.trim().length < 3) return [];
    const have = new Set(subjects.map((s) => s.code));
    return catalog.filter((c) => !have.has(c.code) && matches(query, c.code, c.name)).slice(0, 6);
  }, [query, catalog, subjects]);

  return (
    <>
      <section className="mx-auto flex max-w-[1440px] items-start gap-16 px-20 pt-16 pb-14">
        <div className="flex flex-grow flex-col gap-6">
          <p className="font-mono text-[13px] tracking-[0.08em] text-stamp">
            VTU 2022 SCHEME · CSE, ISE, AIML, AIDS &amp; ALLIED
          </p>
          <h1 className="font-display text-[68px] leading-[1.02] font-semibold tracking-[-0.01em]">
            Know which questions<br />keep coming back.
          </h1>
          <p className="max-w-[640px] text-[19px] leading-relaxed text-ink-2">
            Every past VTU paper, grouped by question and ranked by how often it repeats.
            Pick your subject, grab the cheat sheet, study what counts.
          </p>
          <label className="mt-2 flex h-16 w-[720px] items-center gap-3.5 rounded-[14px] border-[1.5px] border-ink bg-surface px-5">
            <SearchIcon size={22} className="text-ink-2" />
            <span className="sr-only">Search subjects</span>
            <input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by code or name — BCS502, Computer Networks…"
              className="flex-grow bg-transparent text-lg text-ink outline-none placeholder:text-ink-3" />
            <kbd className="rounded-md border border-line px-2 py-0.5 font-mono text-[13px] text-ink-2">/</kbd>
          </label>
          <p className="text-sm text-ink-2">
            {subjects.length > 0
              ? `${plural(subjects.length, "subject")} ranked so far — results appear as you type.`
              : "The bank is empty right now — upload the first paper to get it started."}
          </p>
        </div>
        {aside}
      </section>

      <section className="mx-auto flex max-w-[1440px] flex-col gap-6 px-20 pb-14">
        <div className="flex items-baseline gap-3.5">
          <h2 className="font-display text-[34px] font-semibold">{query ? "Matching subjects" : "All subjects"}</h2>
          <span className="font-mono text-[15px] text-ink-2">{shown.length}</span>
          <div className="flex-grow" />
          <label htmlFor="sort" className="text-sm text-ink-2">Sort</label>
          <select id="sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}
            className="h-10 rounded-[10px] border border-line bg-surface px-3 text-sm text-ink">
            <option value="papers">Most papers</option>
            <option value="recent">Recently updated</option>
            <option value="code">Subject code</option>
          </select>
        </div>

        {subjects.length > 0 && (
          <div className="flex flex-col gap-3">
            <div role="group" aria-label="Branch" className="flex flex-wrap items-center gap-2">
              <span className="w-[90px] text-sm text-ink-2">Branch</span>
              <Chip label="All" on={!branch} onClick={() => setBranch(null)} />
              {branches.map((b) => <Chip key={b} label={b} on={branch === b} onClick={() => setBranch(branch === b ? null : b)} />)}
            </div>
            <div role="group" aria-label="Semester" className="flex flex-wrap items-center gap-2">
              <span className="w-[90px] text-sm text-ink-2">Semester</span>
              <Chip label="Any" on={!semester} onClick={() => setSemester(null)} />
              {semesters.map((n) => <Chip key={n} label={String(n)} on={semester === n} onClick={() => setSemester(semester === n ? null : n)} />)}
            </div>
          </div>
        )}

        {shown.length > 0 ? (
          <div className="grid grid-cols-3 gap-5">
            {shown.map((s) => (
              <Link key={s.code} href={`/s/${s.code}`}
                className="flex min-h-[196px] flex-col gap-3.5 rounded-[14px] border border-line bg-surface p-6 text-ink transition-colors hover:border-ink">
                <div className="flex items-center justify-between">
                  <span className="rounded-[5px] border-[1.5px] border-stamp px-2 py-0.5 font-mono text-sm font-medium text-stamp">{s.code}</span>
                  <span className="text-[13px] text-ink-2">
                    {s.semester ? `Sem ${s.semester} · ` : ""}{s.branch}
                  </span>
                </div>
                <span className="flex-grow font-display text-2xl leading-tight font-semibold">{s.name}</span>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm text-ink-2">
                    {plural(s.paperCount, "paper")}{s.maxYear ? ` · ${yearRange(s.minYear, s.maxYear)}` : ""}
                  </span>
                  {s.paperCount >= 2 ? (
                    <span className="rounded-full bg-info-bg px-2.5 py-1 text-[13px] font-medium text-info-fg">Cheat sheet ready</span>
                  ) : (
                    <span className="rounded-full bg-mid-bg px-2.5 py-1 text-[13px] font-medium text-mid-fg">Needs 1 more to rank</span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        ) : subjects.length > 0 ? (
          <p className="rounded-[14px] border border-dashed border-line-strong p-8 text-center text-ink-2">
            No ranked subject matches that.
          </p>
        ) : null}

        {missing.length > 0 && (
          <div className="flex flex-col gap-3 rounded-[14px] border border-line bg-paper-2 p-6">
            <h3 className="text-[15px] font-semibold">Not in the bank yet</h3>
            <ul className="grid grid-cols-2 gap-x-8">
              {missing.map((c) => (
                <li key={c.code} className="flex items-center gap-3 border-t border-line-soft py-3 text-[15px]">
                  <span className="w-[92px] font-mono text-[13px] text-stamp">{c.code}</span>
                  <span className="flex-grow">{c.name}</span>
                  <Link href={`/upload?subject=${c.code}`} className="text-sm font-medium text-accent">Upload a paper →</Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </>
  );
}
