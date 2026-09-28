// Deterministic formatting (same output on the server and in the browser,
// so server-rendered pages never mismatch on hydration).

const dateFmt = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata",
});

export function formatDate(iso: string | null | undefined): string {
  return iso ? dateFmt.format(new Date(iso)) : "";
}

export function yearRange(min: number | null, max: number | null): string {
  if (!min && !max) return "";
  if (!min || min === max) return String(max);
  return `${min}–${max}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
