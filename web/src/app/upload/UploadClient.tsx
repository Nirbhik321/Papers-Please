"use client";

import Link from "next/link";
import Script from "next/script";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CheckIcon, FileIcon, ShieldIcon, UploadIcon } from "@/components/Icons";
import { PUBLIC_API } from "@/lib/api";
import type { CatalogEntry, UploadStatus } from "@/lib/types";
import { TURNSTILE_SITE_KEY, mountTurnstile, nextToken, unmountTurnstile } from "./turnstile";

const MAX_MB = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB || 10);
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const STORE = "papers-please:uploads";

type Item = {
  localId: string;
  filename: string;
  sizeMb: number;
  id?: number;
  token?: string;
  status?: UploadStatus;
  error?: string;        // refused before or at upload
  note?: string;         // e.g. duplicate of a file we already have
  sending?: boolean;
};

const STEPS = ["Uploaded", "Read safely", "Confirm details", "Matched", "Live"];

function progress(item: Item): { current: number; tone: "active" | "review" | "error" | "done" } {
  const s = item.status;
  if (item.error) return { current: 0, tone: "error" };
  if (!s) return { current: 0, tone: "active" };
  if (s.status === "rejected" || s.status === "failed") return { current: s.stage === "done" && s.questionCount ? 3 : 1, tone: "error" };
  if (s.status === "awaiting_confirmation") return { current: 2, tone: "active" };
  if (s.status === "review") return { current: 3, tone: "review" };
  if (s.status === "approved") return s.stage === "done" ? { current: 5, tone: "done" } : { current: 4, tone: "active" };
  if (s.stage === "matching") return { current: 3, tone: "active" };
  return { current: 1, tone: "active" };
}

function badge(item: Item): { label: string; cls: string } {
  const s = item.status;
  if (item.error) return { label: "Not accepted", cls: "bg-hi-bg text-hi-fg" };
  if (item.note) return { label: "Already have it", cls: "bg-ok-bg text-ok-fg" };
  if (!s) return { label: "Uploading…", cls: "bg-lo-bg text-lo-fg" };
  switch (s.status) {
    case "awaiting_confirmation": return { label: "Needs your OK", cls: "bg-info-bg text-info-fg" };
    case "review": return { label: "In review", cls: "bg-mid-bg text-mid-fg" };
    case "approved": return s.stage === "done"
      ? { label: "Live", cls: "bg-ok-bg text-ok-fg" } : { label: "Publishing…", cls: "bg-info-bg text-info-fg" };
    case "rejected": return { label: "Not accepted", cls: "bg-hi-bg text-hi-fg" };
    case "failed": return { label: "Couldn't finish", cls: "bg-hi-bg text-hi-fg" };
    default: return { label: s.stage === "matching" ? "Matching…" : "Reading…", cls: "bg-lo-bg text-lo-fg" };
  }
}

function isSettled(item: Item) {
  const s = item.status;
  if (item.error || item.note) return true;
  if (!s) return false;
  return s.status === "awaiting_confirmation" || s.status === "review" || s.status === "rejected"
    || s.status === "failed" || (s.status === "approved" && s.stage === "done");
}

export function UploadClient({ catalog }: { catalog: CatalogEntry[] }) {
  const params = useSearchParams();
  const preset = params.get("subject")?.toUpperCase() || "";
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const [human, setHuman] = useState(!TURNSTILE_SITE_KEY);
  const turnstileEl = useRef<HTMLDivElement>(null);

  // Keep this visit's uploads across a refresh (tokens never leave the tab)
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORE);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring browser-only state after hydration
      if (saved) setItems(JSON.parse(saved) as Item[]);
    } catch {}
    return () => unmountTurnstile();
  }, []);
  useEffect(() => {
    try {
      sessionStorage.setItem(STORE, JSON.stringify(items.filter((i) => !i.sending)));
    } catch {}
  }, [items]);

  const patch = useCallback((localId: string, p: Partial<Item>) => {
    setItems((all) => all.map((i) => (i.localId === localId ? { ...i, ...p } : i)));
  }, []);

  // Poll unsettled uploads every 2 s
  useEffect(() => {
    const pending = items.filter((i) => i.id && i.token && !isSettled(i));
    if (!pending.length) return;
    const timer = setTimeout(async () => {
      for (const item of pending) {
        try {
          const r = await fetch(`${PUBLIC_API}/api/uploads/${item.id}`, { headers: { "X-Upload-Token": item.token! } });
          if (r.ok) patch(item.localId, { status: (await r.json()) as UploadStatus });
        } catch {}
      }
    }, 2000);
    return () => clearTimeout(timer);
  }, [items, patch]);

  async function send(file: File) {
    const localId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const item: Item = { localId, filename: file.name, sizeMb: file.size / 1048576, sending: true };
    setItems((all) => [item, ...all]);

    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      return patch(localId, { sending: false, error: "Only PDF files can be uploaded." });
    }
    if (file.size > MAX_MB * 1048576) {
      return patch(localId, { sending: false, error: `This file is ${item.sizeMb.toFixed(1)} MB — the limit is ${MAX_MB} MB.` });
    }
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("cf-turnstile-response", await nextToken());
      const r = await fetch(`${PUBLIC_API}/api/uploads`, { method: "POST", body: form });
      const body = await r.json().catch(() => ({}));
      if (r.status === 201) return patch(localId, { sending: false, id: body.id, token: body.token });
      if (r.status === 409) return patch(localId, { sending: false, note: body.message });
      patch(localId, { sending: false, error: body.detail || "The upload didn't go through. Try again." });
    } catch {
      patch(localId, { sending: false, error: "Couldn't reach the server. Check your connection and try again." });
    }
  }

  function onFiles(list: FileList | null) {
    if (!list) return;
    Array.from(list).slice(0, 10).forEach((f) => void send(f));
  }

  return (
    <main className="mx-auto flex max-w-[1440px] items-start gap-12 px-20 pt-12 pb-8">
      {TURNSTILE_SITE_KEY && (
        <Script src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
          onReady={() => { if (turnstileEl.current) { mountTurnstile(turnstileEl.current); setHuman(true); } }} />
      )}

      <section className="flex min-w-0 flex-grow flex-col gap-6">
        <div className="flex flex-col gap-2.5">
          <h1 className="font-display text-5xl font-semibold">Add a question paper</h1>
          <p className="max-w-[700px] text-[17px] leading-relaxed text-ink-2">
            Every upload is checked and read before it touches any subject. Most papers go live within a couple of
            minutes; anything unusual waits for a moderator.
            {preset && <> You&apos;re adding a paper for <strong className="text-ink">{preset}</strong>.</>}
          </p>
        </div>

        <label
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); onFiles(e.dataTransfer.files); }}
          className={`flex cursor-pointer flex-col items-center gap-3 rounded-[18px] border-2 border-dashed p-11 text-center transition-colors ${
            dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-paper-2 hover:border-ink-3"}`}>
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-ink text-inverse"><UploadIcon size={26} /></span>
          <span className="font-display text-2xl font-semibold">Drop PDFs here, or browse</span>
          <span className="text-[15px] text-ink-2">PDF only · up to {MAX_MB} MB each · 6 pages max · several files at once</span>
          <input type="file" accept="application/pdf,.pdf" multiple className="sr-only"
            onChange={(e) => { onFiles(e.target.files); e.target.value = ""; }} />
        </label>

        <div className="flex items-center gap-3.5">
          {TURNSTILE_SITE_KEY ? (
            <div ref={turnstileEl} className="min-h-[65px]" />
          ) : (
            <span className="flex h-[52px] items-center gap-2.5 rounded-[10px] border border-line bg-surface px-4 text-sm">
              <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-ok-fg text-surface"><CheckIcon size={14} strokeWidth={3} /></span>
              {human ? "Human check not required locally" : "Loading human check…"}
            </span>
          )}
          <span className="text-sm text-ink-2">
            Tip: files named like <span className="font-mono text-ink">JAN 2025 BCS502.pdf</span> need fewer corrections.
          </span>
        </div>

        {items.length > 0 && <h2 className="mt-3 text-base font-semibold text-ink-2">Your uploads · this visit</h2>}
        {items.map((item) => (
          <UploadCard key={item.localId} item={item} catalog={catalog} preset={preset}
            onUpdate={(status) => patch(item.localId, { status })} />
        ))}
      </section>

      <aside className="flex w-[400px] shrink-0 flex-col gap-5">
        <div className="flex flex-col gap-5 rounded-2xl border border-line bg-surface p-7">
          <h2 className="font-display text-2xl font-semibold">What happens to your file</h2>
          {[
            ["Quick checks", `A real PDF, under ${MAX_MB} MB, 6 pages or fewer, not password-protected.`],
            ["Read in a sealed sandbox", "Parsing runs in an isolated process with strict time and memory limits, then it's thrown away."],
            ["Matched against the bank", "Exact copies and re-scans of a paper we already have are caught, so nothing is counted twice."],
            ["Published or reviewed", "Clean, new papers go live automatically. Anything unusual waits for a moderator."],
          ].map(([title, body], i) => (
            <div key={title} className="flex gap-3.5">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-[1.5px] border-ink font-mono text-[13px]">{i + 1}</span>
              <div className="flex flex-col gap-1">
                <span className="text-[15px] font-semibold">{title}</span>
                <span className="text-sm leading-normal text-ink-2">{body}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="flex items-start gap-3.5 rounded-2xl bg-ink p-6 text-inverse">
          <ShieldIcon size={24} className="shrink-0" />
          <span className="text-[14.5px] leading-relaxed">
            Your original PDF is never shown to anyone. Students only ever see the questions we extract and the cheat
            sheet we generate.
          </span>
        </div>
      </aside>
    </main>
  );
}

function Stepper({ item }: { item: Item }) {
  const { current, tone } = progress(item);
  return (
    <ol aria-label="Progress" className="flex items-center gap-2.5">
      {STEPS.map((label, i) => {
        const done = i < current || (tone === "done" && i <= current);
        const here = i === current && tone !== "done";
        const ring = here
          ? tone === "error" ? "border-hi-fg text-hi-fg" : tone === "review" ? "border-mid-fg text-mid-fg" : "border-accent text-accent"
          : done ? "border-accent bg-accent text-surface" : "border-line-strong text-ink-3";
        return (
          <li key={label} className="flex flex-1 items-center gap-2.5">
            <span className={`flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border-2 font-mono text-xs font-medium ${ring}`}>
              {done ? <CheckIcon size={14} strokeWidth={3} /> : i + 1}
            </span>
            <span className={`text-sm whitespace-nowrap ${here ? "font-semibold text-ink" : done ? "text-ink" : "text-ink-2"}`}>
              {here && tone === "review" ? "In review" : label}
            </span>
            {i < STEPS.length - 1 && <span className={`h-0.5 flex-grow ${done ? "bg-accent" : "bg-line"}`} />}
          </li>
        );
      })}
    </ol>
  );
}

function UploadCard({ item, catalog, preset, onUpdate }: {
  item: Item; catalog: CatalogEntry[]; preset: string; onUpdate: (s: UploadStatus) => void;
}) {
  const s = item.status;
  const b = badge(item);
  const message = item.error || item.note || s?.reason;
  const confirming = s?.status === "awaiting_confirmation";

  return (
    <article className={`flex flex-col gap-5 rounded-2xl bg-surface px-7 py-6 ${confirming ? "border-[1.5px] border-ink" : "border border-line"}`}>
      <div className="flex items-center gap-3.5">
        <FileIcon size={22} className="shrink-0 text-ink-2" />
        <span className="flex-grow text-base font-semibold">
          {item.filename}
          <span className="font-normal text-ink-2">
            {" "}· {item.sizeMb.toFixed(1)} MB{s?.pageCount ? ` · ${s.pageCount} pages` : ""}
          </span>
        </span>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[13px] font-semibold ${b.cls}`}>{b.label}</span>
      </div>

      {!item.error && !item.note && <Stepper item={item} />}

      {message && <p className="text-[14.5px] leading-normal text-ink-2">{message}</p>}

      {s?.status === "approved" && s.stage === "done" && s.subjectCode && (
        <p className="text-[14.5px]">
          Added to <strong>{s.subjectCode} {s.subjectName}</strong>.{" "}
          <Link href={`/s/${s.subjectCode}`} className="font-medium text-accent">Open the subject →</Link>
        </p>
      )}

      {confirming && item.id && item.token && (
        <ConfirmForm id={item.id} token={item.token} status={s} catalog={catalog} preset={preset} onUpdate={onUpdate} />
      )}
    </article>
  );
}

function ConfirmForm({ id, token, status, catalog, preset, onUpdate }: {
  id: number; token: string; status: UploadStatus; catalog: CatalogEntry[]; preset: string; onUpdate: (s: UploadStatus) => void;
}) {
  const thisYear = new Date().getFullYear();
  const [code, setCode] = useState(status.subjectCode || preset);
  const [month, setMonth] = useState(status.examMonth || "");
  const [year, setYear] = useState(status.examYear ? String(status.examYear) : "");
  const [type, setType] = useState<"see" | "model">(status.paperType || "see");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const known = catalog.find((c) => c.code === code.trim().toUpperCase());

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`${PUBLIC_API}/api/uploads/${id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Upload-Token": token },
        body: JSON.stringify({
          subjectCode: code.trim().toUpperCase(),
          examYear: year ? Number(year) : null,
          examMonth: type === "see" ? month || null : null,
          paperType: type,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) setError(body.detail || "That didn't work — check the details and try again.");
      else onUpdate(body as UploadStatus);
    } catch {
      setError("Couldn't reach the server. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const field = "h-11 rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink";
  return (
    <form onSubmit={submit} className="flex flex-col gap-4 rounded-xl bg-surface-2 p-[22px]">
      <span className="text-[15px] font-semibold">We read this as — correct anything that&apos;s off:</span>
      <div className="grid grid-cols-4 gap-3.5">
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`subj-${id}`} className="text-[13px] text-ink-2">Subject code</label>
          <input id={`subj-${id}`} list="subject-codes" value={code} onChange={(e) => setCode(e.target.value)}
            required maxLength={12} placeholder="e.g. BCS502" className={`${field} font-mono uppercase`} />
          <span className="truncate text-xs text-ink-2">{known ? known.name : code ? "Not in our subject list — a moderator will check" : ""}</span>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`type-${id}`} className="text-[13px] text-ink-2">Paper type</label>
          <select id={`type-${id}`} value={type} onChange={(e) => setType(e.target.value as "see" | "model")} className={field}>
            <option value="see">Semester-end exam</option>
            <option value="model">Model question paper</option>
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`month-${id}`} className="text-[13px] text-ink-2">Exam month</label>
          <select id={`month-${id}`} value={month} onChange={(e) => setMonth(e.target.value)} disabled={type === "model"}
            required={type === "see"} className={`${field} disabled:opacity-50`}>
            <option value="">Pick…</option>
            {MONTHS.map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`year-${id}`} className="text-[13px] text-ink-2">Year</label>
          <select id={`year-${id}`} value={year} onChange={(e) => setYear(e.target.value)} required={type === "see"} className={field}>
            <option value="">Pick…</option>
            {Array.from({ length: thisYear + 2 - 2015 }, (_, i) => thisYear + 1 - i).map((y) => <option key={y}>{y}</option>)}
          </select>
        </div>
      </div>
      <datalist id="subject-codes">
        {catalog.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
      </datalist>

      <p className="text-sm text-ink-2">
        <strong className="text-ink">{status.questionCount} questions</strong> found across {status.modulesFound} of 5 modules. A few of them:
      </p>
      <ul>
        {status.preview.map((q) => (
          <li key={`${q.module}-${q.where}`} className="flex gap-4 border-t border-line py-2.5 text-[14.5px]">
            <span className="w-[120px] shrink-0 font-mono text-[13px] text-ink-2">
              M{q.module} · {q.where}{q.marks ? ` · ${q.marks}M` : ""}
            </span>
            <span>{q.text}</span>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="rounded-lg bg-hi-bg px-3.5 py-2.5 text-sm text-hi-fg">{error}</p>}
      <div className="flex items-center gap-3">
        <button type="submit" disabled={busy}
          className="h-12 cursor-pointer rounded-[10px] bg-ink px-[22px] text-[15px] font-semibold text-inverse disabled:opacity-60">
          {busy ? "Submitting…" : "Looks right — submit"}
        </button>
        <span className="ml-2 text-[13px] text-ink-2">Nothing goes public until you submit.</span>
      </div>
    </form>
  );
}
