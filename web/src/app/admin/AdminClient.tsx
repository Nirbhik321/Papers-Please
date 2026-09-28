"use client";

import { useCallback, useEffect, useState } from "react";
import { Logo } from "@/components/SiteHeader";
import { ThemeToggle } from "@/components/ThemeToggle";
import { PUBLIC_API } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { AdminPaper, AdminPaperDetail } from "@/lib/types";

const SUPABASE_URL = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").replace(/\/$/, "");
const SUPABASE_ANON = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
const TOKEN_KEY = "papers-please:admin-token";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];

const VIEWS = [
  { status: "review", label: "Needs review" },
  { status: "awaiting_confirmation", label: "Awaiting uploader" },
  { status: "failed", label: "Failed" },
  { status: "processing", label: "Processing" },
  { status: "approved", label: "Live papers" },
  { status: "rejected", label: "Rejected" },
] as const;

type ApiError = Error & { status?: number };

async function api<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`${PUBLIC_API}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(init.headers || {}) },
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(body.detail || `Request failed (${r.status})`) as ApiError;
    err.status = r.status;
    throw err;
  }
  return body as T;
}

export function AdminClient() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring the session after hydration
      setToken(sessionStorage.getItem(TOKEN_KEY));
    } catch {}
    setReady(true);
  }, []);

  function signIn(t: string) {
    try { sessionStorage.setItem(TOKEN_KEY, t); } catch {}
    setToken(t);
  }
  function signOut() {
    try { sessionStorage.removeItem(TOKEN_KEY); } catch {}
    setToken(null);
  }

  if (!ready) return null;
  return token ? <Dashboard token={token} onSignOut={signOut} /> : <SignIn onSignIn={signIn} />;
}

// ── Sign in ───────────────────────────────────────────────────────────────────

function SignIn({ onSignIn }: { onSignIn: (token: string) => void }) {
  const [email, setEmail] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const supabase = Boolean(SUPABASE_URL && SUPABASE_ANON);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let token = secret.trim();
      if (supabase) {
        const r = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
          method: "POST",
          headers: { apikey: SUPABASE_ANON, "Content-Type": "application/json" },
          body: JSON.stringify({ email, password: secret }),
        });
        const body = await r.json();
        if (!r.ok) throw new Error(body.error_description || body.msg || "Wrong email or password.");
        token = body.access_token;
      }
      await api(token, "/api/admin/me");
      onSignIn(token);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const field = "h-12 rounded-[10px] border border-line-strong bg-surface px-3.5 text-[15px] text-ink";
  return (
    <main className="flex min-h-screen items-center justify-center">
      <form onSubmit={submit} className="flex w-[420px] flex-col gap-4 rounded-2xl border border-line bg-surface p-8">
        <Logo />
        <h1 className="mt-2 font-display text-3xl font-semibold">Moderator sign in</h1>
        {supabase && (
          <label className="flex flex-col gap-1.5 text-sm text-ink-2">
            Email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" className={field} />
          </label>
        )}
        <label className="flex flex-col gap-1.5 text-sm text-ink-2">
          {supabase ? "Password" : "Moderator token"}
          <input type="password" required value={secret} onChange={(e) => setSecret(e.target.value)}
            autoComplete={supabase ? "current-password" : "off"} className={field} />
        </label>
        {error && <p role="alert" className="rounded-lg bg-hi-bg px-3.5 py-2.5 text-sm text-hi-fg">{error}</p>}
        <button type="submit" disabled={busy}
          className="h-12 cursor-pointer rounded-[10px] bg-ink text-[15px] font-semibold text-inverse disabled:opacity-60">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

function Dashboard({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const [user, setUser] = useState("");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [view, setView] = useState<string>("review");
  const [rows, setRows] = useState<AdminPaper[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<AdminPaperDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [flash, setFlash] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  const fail = useCallback((err: unknown) => {
    if ((err as ApiError).status === 401) return onSignOut();
    setFlash({ tone: "err", text: (err as Error).message });
  }, [onSignOut]);

  const refresh = useCallback(async () => {
    try {
      const [me, list] = await Promise.all([
        api<{ user: string; counts: Record<string, number> }>(token, "/api/admin/me"),
        api<AdminPaper[]>(token, `/api/admin/papers${view === "all" ? "" : `?status=${view}`}`),
      ]);
      setUser(me.user);
      setCounts(me.counts);
      setRows(list);
    } catch (err) {
      fail(err);
    }
  }, [token, view, fail]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on view change
    void refresh();
  }, [refresh]);

  const loadDetail = useCallback(async (id: number) => {
    setSelected(id);
    setLoadingDetail(true);
    try {
      setDetail(await api<AdminPaperDetail>(token, `/api/admin/papers/${id}`));
    } catch (err) {
      fail(err);
    } finally {
      setLoadingDetail(false);
    }
  }, [token, fail]);

  async function act(label: string, path: string, init: RequestInit, after: "reload" | "close" = "reload") {
    setFlash(null);
    try {
      await api(token, path, init);
      setFlash({ tone: "ok", text: label });
      await refresh();
      if (after === "close" || !selected) {
        setSelected(null);
        setDetail(null);
      } else {
        await loadDetail(selected);
      }
    } catch (err) {
      fail(err);
    }
  }

  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-[72px] items-center gap-5 border-b border-line bg-surface px-10">
        <Logo />
        <span className="rounded-full bg-ink px-2.5 py-1 text-[13px] font-semibold text-inverse">Moderation</span>
        <div className="flex-grow" />
        <span className="text-sm text-ink-2">Signed in as {user}</span>
        <ThemeToggle />
        <button type="button" onClick={onSignOut}
          className="h-11 cursor-pointer rounded-[10px] border border-line px-4 text-sm font-medium hover:border-line-strong">
          Sign out
        </button>
      </header>

      <div className="flex flex-grow">
        <nav aria-label="Moderation" className="flex w-[250px] shrink-0 flex-col gap-1 border-r border-line px-4 py-7">
          {[...VIEWS, { status: "all", label: "All uploads" }].map((v) => {
            const on = view === v.status;
            const n = v.status === "all" ? total : counts[v.status] || 0;
            return (
              <button key={v.status} type="button" onClick={() => { setView(v.status); setSelected(null); setDetail(null); }}
                className={`flex h-11 cursor-pointer items-center justify-between rounded-[10px] px-3.5 text-left text-[15px] ${
                  on ? "bg-ink font-semibold text-inverse" : "text-ink hover:bg-surface"}`}>
                <span>{v.label}</span>
                <span className="font-mono text-[13px]">{n}</span>
              </button>
            );
          })}
        </nav>

        <main className="flex min-w-0 flex-grow flex-col gap-6 px-12 py-9">
          <div className="flex flex-col gap-1.5">
            <h1 className="font-display text-[38px] font-semibold">
              {[...VIEWS, { status: "all", label: "All uploads" }].find((v) => v.status === view)?.label}
            </h1>
            <p className="text-[15px] text-ink-2">
              {view === "review"
                ? `${rows.length} upload${rows.length === 1 ? "" : "s"} need a decision. Nothing here affects what students see until you approve it.`
                : view === "awaiting_confirmation"
                  ? "Read successfully, waiting for the uploader to confirm the subject and session. You can confirm them yourself by editing and approving."
                  : `${rows.length} paper${rows.length === 1 ? "" : "s"}.`}
            </p>
          </div>

          {flash && (
            <p role="status" className={`rounded-[10px] px-4 py-3 text-sm ${flash.tone === "ok" ? "bg-ok-bg text-ok-fg" : "bg-hi-bg text-hi-fg"}`}>
              {flash.text}
            </p>
          )}

          <div className="overflow-hidden rounded-[14px] border border-line bg-surface">
            <table className="w-full border-collapse text-[14.5px]">
              <thead>
                <tr className="bg-surface-2 text-left text-[13px] text-ink-2">
                  <th className="px-4 py-3 font-semibold">File</th>
                  <th className="px-4 py-3 font-semibold">Detected as</th>
                  <th className="px-4 py-3 font-semibold">Why it&apos;s here</th>
                  <th className="px-4 py-3 font-semibold">Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-ink-2">Nothing here.</td></tr>
                )}
                {rows.map((r) => (
                  <tr key={r.id} onClick={() => loadDetail(r.id)}
                    className={`cursor-pointer border-t border-line-soft ${selected === r.id ? "bg-accent-soft" : "hover:bg-surface-2"}`}>
                    <td className={`border-l-[3px] px-4 py-3.5 font-medium ${selected === r.id ? "border-accent" : "border-transparent"}`}>
                      <button type="button" className="cursor-pointer text-left">{r.filename}</button>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-[13.5px]">{r.subjectCode || "—"} · {r.session}</td>
                    <td className="max-w-[440px] px-4 py-3.5 text-ink-2">{r.reason || statusText(r)}</td>
                    <td className="px-4 py-3.5 whitespace-nowrap text-ink-2">
                      {formatDate(r.createdAt)} · {r.uploader === "seed" ? "seed" : `ip·${(r.uploader || "").slice(0, 4)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selected && (loadingDetail && !detail ? (
            <div className="h-64 animate-pulse rounded-2xl border border-line bg-surface" />
          ) : detail && (
            <Detail paper={detail} act={act} />
          ))}
        </main>
      </div>
    </div>
  );
}

function statusText(p: AdminPaper) {
  if (p.status === "approved") return `Live · approved by ${p.reviewedBy || "?"}`;
  if (p.status === "processing") return `Processing (${p.stage})`;
  if (p.status === "awaiting_confirmation") return `${p.questionCount} questions read · waiting for the uploader`;
  return p.status;
}

type Act = (label: string, path: string, init: RequestInit, after?: "reload" | "close") => Promise<void>;

function Detail({ paper: p, act }: { paper: AdminPaperDetail; act: Act }) {
  const [reason, setReason] = useState("");
  const [code, setCode] = useState(p.subjectCode || "");
  const [type, setType] = useState<"see" | "model">(p.paperType);
  const [month, setMonth] = useState(p.examMonth || "");
  const [year, setYear] = useState(p.examYear ? String(p.examYear) : "");
  const [showQuestions, setShowQuestions] = useState(false);
  const live = p.status === "approved";
  const cmp = p.comparison;
  const post = { method: "POST" };
  const btn = "h-[46px] cursor-pointer rounded-[10px] px-[18px] text-[15px] font-medium disabled:opacity-50";

  return (
    <section className="flex flex-col gap-5 rounded-2xl border border-line bg-surface p-7">
      <div className="flex items-center gap-3.5">
        <h2 className="flex-grow font-display text-2xl font-semibold">
          #{p.id} {p.filename}
        </h2>
        {cmp && (
          <span className={`rounded-full px-3 py-1.5 text-sm font-semibold ${cmp.score >= 0.9 ? "bg-mid-bg text-mid-fg" : "bg-lo-bg text-lo-fg"}`}>
            {Math.round(cmp.score * 100)}% of questions match {cmp.against.subjectCode} {cmp.against.session}
          </span>
        )}
      </div>
      <p className="text-sm text-ink-2">
        {p.status} · {p.pdfType || "?"} · {p.pageCount ?? "?"} pages · {p.questionCount ?? 0} questions in {p.modulesFound ?? 0} of 5 modules
        {p.detected?.subjectCode ? ` · filename/content suggested ${p.detected.subjectCode}` : ""}
      </p>
      {p.reason && <p className="rounded-[10px] bg-surface-2 px-4 py-3 text-[15px]">{p.reason}</p>}

      {!live && (
        <form className="grid grid-cols-5 items-end gap-3" onSubmit={(e) => {
          e.preventDefault();
          void act("Details saved.", `/api/admin/papers/${p.id}`, {
            method: "PATCH",
            body: JSON.stringify({ subjectCode: code, paperType: type, examMonth: type === "see" ? month || null : null, examYear: year ? Number(year) : null }),
          });
        }}>
          <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">Subject code
            <input value={code} onChange={(e) => setCode(e.target.value)} className="h-11 rounded-lg border border-line-strong bg-surface px-2.5 font-mono text-sm text-ink uppercase" />
          </label>
          <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">Type
            <select value={type} onChange={(e) => setType(e.target.value as "see" | "model")} className="h-11 rounded-lg border border-line-strong bg-surface px-2 text-sm text-ink">
              <option value="see">Semester-end</option><option value="model">Model paper</option>
            </select>
          </label>
          <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">Month
            <select value={month} onChange={(e) => setMonth(e.target.value)} disabled={type === "model"} className="h-11 rounded-lg border border-line-strong bg-surface px-2 text-sm text-ink disabled:opacity-50">
              <option value="">—</option>{MONTHS.map((m) => <option key={m}>{m}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">Year
            <input value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} className="h-11 rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink" />
          </label>
          <button type="submit" className={`${btn} border border-line-strong bg-surface text-ink`}>Save details</button>
        </form>
      )}

      {cmp && (
        <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line-soft">
          <div className="bg-surface-2 px-4 py-3 text-[13px] font-semibold text-ink-2">This upload</div>
          <div className="border-l border-line-soft bg-surface-2 px-4 py-3 text-[13px] font-semibold text-ink-2">
            Closest live paper · #{cmp.against.id} {cmp.against.session} ({cmp.against.status})
          </div>
          {cmp.pairs.slice(0, 12).map((pair, i) => (
            <div key={i} className="contents">
              <div className="border-t border-line-soft px-4 py-2.5 text-sm leading-snug">
                <span className="mr-2 font-mono text-[12.5px] text-ink-2">{pair.a.where}</span>{pair.a.text}
              </div>
              <div className="flex gap-3 border-t border-l border-line-soft px-4 py-2.5 text-sm leading-snug">
                <span className="flex-grow"><span className="mr-2 font-mono text-[12.5px] text-ink-2">{pair.b.where}</span>{pair.b.text}</span>
                <span className={`font-mono text-[12.5px] ${pair.similarity >= 0.85 ? "text-ok-fg" : "text-mid-fg"}`}>{pair.similarity.toFixed(2)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div>
        <button type="button" onClick={() => setShowQuestions(!showQuestions)} className="cursor-pointer text-sm font-medium text-accent">
          {showQuestions ? "Hide" : "Show"} all {p.questions.length} extracted questions
        </button>
        {showQuestions && (
          <ul className="mt-2">
            {p.questions.map((q, i) => (
              <li key={i} className="flex gap-4 border-t border-line-soft py-2 text-sm">
                <span className="w-[120px] shrink-0 font-mono text-[12.5px] text-ink-2">M{q.module} · {q.where}{q.marks ? ` · ${q.marks}M` : ""}</span>
                <span>{q.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {!live && (
          <button type="button" className={`${btn} bg-ink text-inverse`}
            onClick={() => act("Approved — the subject is being republished.", `/api/admin/papers/${p.id}/approve`, post)}>
            Approve
          </button>
        )}
        {!live && cmp && cmp.against.status === "approved" && (
          <button type="button" className={`${btn} border border-line-strong bg-surface text-ink`}
            onClick={() => act(`Replaced #${cmp.against.id}.`, `/api/admin/papers/${p.id}/replace`, { ...post, body: JSON.stringify({ replaces: cmp.against.id }) })}>
            Replace live copy with this one
          </button>
        )}
        {!live && p.status !== "processing" && (
          <button type="button" className={`${btn} border border-line-strong bg-surface text-ink`}
            onClick={() => act("Queued for reprocessing.", `/api/admin/papers/${p.id}/reprocess`, post)}>
            Reprocess
          </button>
        )}
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (shown to the uploader)"
          aria-label="Rejection reason" className="h-[46px] w-[280px] rounded-[10px] border border-line-strong bg-surface px-3 text-sm text-ink" />
        {p.status !== "rejected" && (
          <button type="button" className={`${btn} border border-line-strong bg-surface text-ink`}
            onClick={() => act(live ? "Taken down — the subject is being republished." : "Rejected.",
              `/api/admin/papers/${p.id}/reject`, { ...post, body: JSON.stringify({ reason }) })}>
            {live ? "Take down" : "Reject"}
          </button>
        )}
        <div className="flex-grow" />
        {p.uploader && p.uploader !== "seed" && (
          <button type="button" className={`${btn} border border-hi-fg/40 bg-surface text-hi-fg`}
            onClick={() => { if (confirm(`Block all future uploads from ip·${p.uploader?.slice(0, 4)}?`)) void act("Uploader blocked.", `/api/admin/uploaders/${p.uploader}/block`, { ...post, body: JSON.stringify({ reason }) }); }}>
            Block uploader
          </button>
        )}
        <button type="button" className={`${btn} border border-hi-fg/40 bg-surface text-hi-fg`}
          onClick={() => { if (confirm(`Permanently delete #${p.id} and its file?`)) void act("Deleted.", `/api/admin/papers/${p.id}`, { method: "DELETE" }, "close"); }}>
          Delete
        </button>
      </div>
    </section>
  );
}
