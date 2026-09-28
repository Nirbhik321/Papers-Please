import type { CatalogEntry, RecentPaper, Stats, SubjectData, SubjectSummary } from "./types";

/** API base for the browser (uploads, downloads, moderation). */
export const PUBLIC_API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

/** API base for server-side rendering — can be a private URL, falls back to the public one. */
const SERVER_API = (process.env.API_URL || PUBLIC_API).replace(/\/$/, "");

const REVALIDATE = 300; // pages refresh at most every 5 min, or immediately via /api/revalidate

const building = process.env.NEXT_PHASE === "phase-production-build";

export class NotFound extends Error {}

async function get<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${SERVER_API}${path}`, { next: { revalidate: REVALIDATE } });
    if (res.status === 404) throw new NotFound(path);
    if (!res.ok) throw new Error(`${path} → ${res.status}`);
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof NotFound) throw err;
    // At build time the API may be asleep or unreachable: build with empty data
    // and let ISR fill pages in. At runtime, throwing keeps the last good page.
    if (building) return fallback;
    throw err;
  }
}

export const getSubjects = () => get<SubjectSummary[]>("/api/subjects", []);
export const getCatalog = () => get<CatalogEntry[]>("/api/catalog", []);
export const getStats = () => get<Stats>("/api/stats", { papers: 0, subjects: 0, updatedAt: null });
export const getRecent = () => get<RecentPaper[]>("/api/recent?limit=5", []);
export const getSubject = (code: string) =>
  get<SubjectData | null>(`/api/subjects/${encodeURIComponent(code)}`, null);

export function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  const m = s / 60;
  if (m < 60) return `${Math.round(m)} min ago`;
  const h = m / 60;
  if (h < 36) return `${Math.round(h)} h ago`;
  const d = h / 24;
  if (d < 14) return `${Math.round(d)} days ago`;
  if (d < 60) return `${Math.round(d / 7)} weeks ago`;
  return new Date(iso).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

export function yearRange(min: number | null, max: number | null): string {
  if (!min && !max) return "";
  if (min === max || !min) return String(max);
  return `${min}–${max}`;
}
