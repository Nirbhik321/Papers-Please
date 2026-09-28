"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";
import { CheckIcon, DownloadIcon, GraphIcon, ListIcon, PrinterIcon } from "@/components/Icons";
import { PUBLIC_API } from "@/lib/api";
import { formatDate, plural } from "@/lib/format";
import type { Module, Session, SubjectData, Topic } from "@/lib/types";
import { useStudied } from "./useStudied";

// The graph (and d3-force) only downloads when someone opens it
const TopicGraph = dynamic(() => import("./TopicGraph"), {
  ssr: false,
  loading: () => <div className="h-[640px] animate-pulse rounded-2xl border border-line bg-surface" />,
});

function likelihood(t: Topic, single: boolean) {
  if (single) return { label: `${Math.round(t.avgMarks)} marks`, cls: "bg-lo-bg text-lo-fg" };
  if (t.frequencyPct >= 0.8) return { label: "Very likely", cls: "bg-hi-bg text-hi-fg" };
  if (t.frequencyPct >= 0.5) return { label: "Likely", cls: "bg-mid-bg text-mid-fg" };
  return { label: "Occasional", cls: "bg-lo-bg text-lo-fg" };
}

function coverage(mod: Module, studied: Set<string>, cap: number) {
  const sum = mod.topics.filter((t) => studied.has(t.key)).reduce((a, t) => a + t.expectedMarks, 0);
  return Math.round(Math.min(sum, cap));
}

export function SubjectView({ data }: { data: SubjectData }) {
  const { studied, toggle } = useStudied(data.code);
  const [moduleNo, setModuleNo] = useState(data.modules[0]?.no ?? 1);
  const [open, setOpen] = useState<string | null>(data.modules[0]?.topics[0]?.key ?? null);
  const [view, setView] = useState<"list" | "graph">("list");

  const single = data.paperCount === 1;
  const cap = data.moduleMarks;
  const current = data.modules.find((m) => m.no === moduleNo) ?? data.modules[0];
  const sessions = useMemo(() => new Map(data.sessions.map((s) => [s.id, s])), [data.sessions]);
  const dated = data.sessions.filter((s) => s.type === "see");
  const span = dated.length > 1 ? `${dated[dated.length - 1].label} – ${dated[0].label}`
    : dated[0]?.label ?? (data.maxYear ? String(data.maxYear) : "");

  const modCov = coverage(current, studied, cap);
  const totals = data.modules.map((m) => ({ no: m.no, cov: coverage(m, studied, cap) }));
  const total = totals.reduce((a, m) => a + m.cov, 0);

  function pickModule(no: number) {
    setModuleNo(no);
    setOpen(data.modules.find((m) => m.no === no)?.topics[0]?.key ?? null);
  }

  function showInList(key: string) {
    const m = data.modules.find((mm) => mm.topics.some((t) => t.key === key));
    if (m) setModuleNo(m.no);
    setOpen(key);
    setView("list");
    requestAnimationFrame(() => document.getElementById(`topic-${key}`)?.scrollIntoView({ block: "center" }));
  }

  return (
    <main className="mx-auto flex max-w-[1440px] flex-col gap-7 px-20 pt-7 pb-8">
      <nav aria-label="Breadcrumb" className="flex gap-2 text-sm text-ink-2">
        <Link href="/" className="text-ink-2 underline-offset-2 hover:underline">Subjects</Link>
        <span>/</span>
        <span>{data.branch}{data.semester ? ` · Semester ${data.semester}` : ""}</span>
        <span>/</span>
        <span className="text-ink">{data.code}</span>
      </nav>

      <div className="flex items-end gap-10">
        <div className="flex flex-grow flex-col gap-3">
          <span className="-rotate-2 self-start rounded-md border-2 border-stamp px-3 py-0.5 font-mono text-[15px] font-medium tracking-[0.04em] text-stamp">
            {data.code}
          </span>
          <h1 className="font-display text-[56px] leading-[1.05] font-semibold">{data.name}</h1>
          <p className="text-[15px] text-ink-2">
            Based on <strong className="text-ink">{plural(data.paperCount, "paper")}</strong>
            {span ? ` · ${span}` : ""}
            {" · "}{plural(data.topicCount, "topic")} · Updated {formatDate(data.updatedAt)}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2" data-no-print>
          <div className="flex gap-2.5">
            <button type="button" onClick={() => window.print()} aria-label="Print this page"
              className="flex h-[52px] w-[52px] cursor-pointer items-center justify-center rounded-xl border border-line bg-surface text-ink hover:border-line-strong">
              <PrinterIcon />
            </button>
            <a href={`${PUBLIC_API}/api/subjects/${data.code}/questions.csv`}
              className="flex h-[52px] items-center rounded-xl border border-line bg-surface px-5 text-[15px] font-medium text-ink hover:border-line-strong">
              Question bank (CSV)
            </a>
            <a href={`${PUBLIC_API}/api/subjects/${data.code}/cheatsheet.pdf`}
              className="flex h-[52px] items-center gap-2.5 rounded-xl bg-stamp px-[22px] text-base font-semibold text-white hover:opacity-90 dark:text-inverse">
              <DownloadIcon /> Download cheat sheet
            </a>
          </div>
          <span className="text-[13px] text-ink-2">PDF · ready instantly</span>
        </div>
      </div>

      {single && (
        <p className="rounded-xl border border-line bg-info-bg px-5 py-3.5 text-[15px] text-info-fg">
          Only one paper so far, so nothing can repeat yet — topics are ranked by marks.{" "}
          <Link href={`/upload?subject=${data.code}`} className="font-semibold text-info-fg underline">
            Upload another {data.code} paper
          </Link>{" "}to unlock the repeat ranking.
        </p>
      )}

      <div className="flex items-start gap-10">
        <section className="flex min-w-0 flex-grow flex-col gap-5">
          {view === "list" ? (
            <>
              <div role="tablist" aria-label="Modules" className="flex gap-2.5">
                {data.modules.map((m) => {
                  const active = m.no === current.no;
                  const done = m.topics.filter((t) => studied.has(t.key)).length;
                  return (
                    <button key={m.no} role="tab" aria-selected={active} type="button" onClick={() => pickModule(m.no)}
                      className={`flex flex-1 cursor-pointer flex-col items-start gap-1 rounded-xl border px-3.5 py-3 text-left ${
                        active ? "border-ink bg-ink text-inverse" : "border-line bg-surface text-ink hover:border-line-strong"}`}>
                      <span className="text-[15px] font-semibold">Module {m.no}</span>
                      <span className={`text-[12.5px] ${active ? "opacity-80" : "text-ink-2"}`}>
                        {done} of {m.topics.length} studied
                      </span>
                    </button>
                  );
                })}
              </div>
              <ModuleHeader title={`Module ${current.no}`} view={view} setView={setView} single={single} />
              {current.topics.map((t) => (
                <TopicCard key={t.key} topic={t} sessions={data.sessions} lookup={sessions} total={data.paperCount}
                  single={single} studied={studied.has(t.key)} onToggle={() => toggle(t.key)}
                  isOpen={open === t.key} onExpand={() => setOpen(open === t.key ? null : t.key)} />
              ))}
            </>
          ) : (
            <>
              <ModuleHeader title="All modules" view={view} setView={setView} single={single} graph />
              <TopicGraph modules={data.modules} studied={studied} onOpen={showInList} />
            </>
          )}
        </section>

        <aside className="flex w-[380px] shrink-0 flex-col gap-5" data-no-print>
          <div className="flex flex-col gap-3.5 rounded-2xl border border-line bg-surface p-[26px]">
            <span className="text-sm font-semibold text-ink-2">Your coverage · Module {current.no}</span>
            <div className="flex items-baseline gap-2">
              <span className="font-display text-6xl leading-none font-semibold">{modCov}</span>
              <span className="text-lg text-ink-2">/ {cap} marks</span>
            </div>
            <Meter pct={(modCov / cap) * 100} height={12} />
            <p className="text-sm leading-normal text-ink-2">
              Expected marks from topics you&apos;ve marked as studied. Saved on this device — no account needed.
            </p>
            <h3 className="mt-2.5 text-[15px] font-semibold">Marks ladder</h3>
            <ol>
              {current.ladder.map((s) => (
                <li key={s.rank} className={`flex justify-between gap-3 border-t border-line-soft py-2.5 text-[14.5px] ${s.full ? "text-ok-fg" : ""}`}>
                  <span><strong>Top {s.rank}</strong> · {s.label}</span>
                  <span className="shrink-0 font-mono">~{Math.round(s.cumulative)}M</span>
                </li>
              ))}
            </ol>
            <p className="rounded-[10px] bg-ok-bg px-3.5 py-3 text-sm font-medium text-ok-fg">
              {current.fullAt
                ? `Study the top ${plural(current.fullAt, "topic")} to cover the full module.`
                : `All ${plural(current.topics.length, "topic")} together cover ~${Math.round(current.ladder.at(-1)?.cumulative ?? 0)} of ${cap} marks.`}
            </p>
          </div>

          <div className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-[26px]">
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-semibold text-ink-2">Whole subject</span>
              <span className="font-mono text-sm">{total} / {cap * data.modules.length}</span>
            </div>
            {totals.map((m) => (
              <div key={m.no} className="flex items-center gap-3">
                <span className={`w-7 font-mono text-[13px] ${m.no === current.no ? "text-ink" : "text-ink-2"}`}>M{m.no}</span>
                <div className="flex-grow"><Meter pct={(m.cov / cap) * 100} height={8} /></div>
                <span className="w-8 text-right font-mono text-[13px] text-ink-2">{m.cov}</span>
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-1 rounded-2xl border border-line bg-surface p-[26px]">
            <span className="mb-2 text-sm font-semibold text-ink-2">Papers in this analysis</span>
            {data.sessions.map((s) => (
              <div key={s.id} className="flex justify-between border-t border-line-soft py-2 text-sm">
                <span>{s.label}</span>
                <span className="text-ink-2">
                  {s.type === "model" ? "Model paper" : "Semester-end"} · {s.source === "scanned" ? "scanned" : "digital"}
                </span>
              </div>
            ))}
            <Link href={`/upload?subject=${data.code}`} className="mt-2.5 text-sm font-medium text-accent">
              Have one we&apos;re missing? Upload it →
            </Link>
          </div>
        </aside>
      </div>
    </main>
  );
}

function Meter({ pct, height }: { pct: number; height: number }) {
  return (
    <div className="overflow-hidden rounded-full bg-line-soft" style={{ height }}>
      <div className="rounded-full bg-accent transition-[width] duration-300" style={{ height, width: `${Math.min(100, pct)}%` }} />
    </div>
  );
}

function ModuleHeader({ title, view, setView, single, graph }: {
  title: string; view: "list" | "graph"; setView: (v: "list" | "graph") => void; single: boolean; graph?: boolean;
}) {
  const btn = (v: "list" | "graph", label: string, icon: React.ReactNode) => (
    <button type="button" aria-pressed={view === v} onClick={() => setView(v)}
      className={`flex h-9 cursor-pointer items-center gap-1.5 rounded-lg px-3.5 text-sm font-medium ${
        view === v ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}>
      {icon}{label}
    </button>
  );
  return (
    <div className="mt-2 flex items-center gap-4" data-no-print>
      <div className="flex flex-grow flex-col gap-1">
        <h2 className="font-display text-3xl font-semibold">{title}</h2>
        <p className="text-sm text-ink-2">
          {graph
            ? "Each dot is a topic — bigger means it repeats more. Click one to open it in the list."
            : single
              ? "Ranked by marks — upload more papers to see which topics repeat."
              : "Ranked by how many papers each topic appeared in — recent papers count a little more."}
        </p>
      </div>
      <div role="group" aria-label="View" className="flex rounded-[10px] bg-line-soft p-1">
        {btn("list", "List", <ListIcon size={16} />)}
        {btn("graph", "Graph", <GraphIcon size={16} />)}
      </div>
    </div>
  );
}

function TopicCard({ topic: t, sessions, lookup, total, single, studied, onToggle, isOpen, onExpand }: {
  topic: Topic; sessions: Session[]; lookup: Map<number, Session>; total: number; single: boolean;
  studied: boolean; onToggle: () => void; isOpen: boolean; onExpand: () => void;
}) {
  const badge = likelihood(t, single);
  const present = new Set(t.sessions);
  return (
    <article id={`topic-${t.key}`}
      className={`flex flex-col gap-4 rounded-[14px] border bg-surface px-7 py-6 ${studied ? "border-accent-line" : "border-line"}`}>
      <div className="flex items-start gap-5">
        <span className="w-7 pt-1 font-mono text-[15px] text-ink-2">{String(t.rank).padStart(2, "0")}</span>
        <div className="flex flex-grow flex-col gap-2.5">
          <div className="flex items-center gap-3">
            <span className={`rounded-full px-2.5 py-1 text-[13px] font-semibold ${badge.cls}`}>{badge.label}</span>
            <span className="text-sm text-ink-2">
              {single ? "In this paper" : `In ${t.frequency} of ${total} papers`}
              {t.avgMarks ? ` · usually ${Math.round(t.avgMarks)} marks` : ""}
              {!single && t.expectedMarks >= 0.5 ? ` · worth ~${Math.round(t.expectedMarks)}M to you` : ""}
            </span>
          </div>
          <h3 className="font-display text-[25px] leading-snug font-semibold">{t.label}</h3>
          <p className="text-base leading-relaxed text-ink-2">“{t.text}”</p>
        </div>
        <button type="button" aria-pressed={studied} onClick={onToggle}
          className={`flex h-11 shrink-0 cursor-pointer items-center gap-2.5 rounded-[10px] border px-3.5 text-sm font-medium text-ink ${
            studied ? "border-accent bg-accent-soft" : "border-line-strong bg-surface hover:border-ink-3"}`}>
          <span className={`flex h-5 w-5 items-center justify-center rounded-[5px] border-[1.5px] ${
            studied ? "border-accent bg-accent text-surface" : "border-ink-3"}`}>
            {studied && <CheckIcon size={14} strokeWidth={3} />}
          </span>
          {studied ? "Studied" : "Mark studied"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 pl-12">
        <span className="w-[84px] text-[13px] text-ink-2">Appeared in</span>
        {sessions.map((s) => (
          <span key={s.id} title={s.label}
            className={`flex h-7 min-w-[66px] items-center justify-center rounded-md px-1.5 font-mono text-xs ${
              present.has(s.id) ? "bg-accent text-surface" : "bg-line-soft text-ink-3"}`}>
            {s.short}
          </span>
        ))}
        <div className="flex-grow" />
        <button type="button" onClick={onExpand} aria-expanded={isOpen}
          className="h-9 cursor-pointer px-1 text-sm font-medium text-accent hover:underline">
          {isOpen ? "Hide" : t.wordings.length === 1 ? "Where it appeared" : `See all ${t.wordings.length} wordings`}
        </button>
      </div>

      {isOpen && (
        <ul className="ml-12 flex flex-col border-t border-line-soft pt-1.5">
          {t.wordings.map((w, i) => (
            <li key={i} className="flex gap-5 border-b border-line-soft py-2.5 last:border-b-0">
              <span className="w-[190px] shrink-0 font-mono text-[13px] text-ink-2">
                {lookup.get(w.session)?.label ?? "Paper"} · {w.where}{w.marks ? ` · ${w.marks}M` : ""}
              </span>
              <span className="text-[15px] leading-normal">{w.text}</span>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
