"use client";

// Cloudflare Turnstile, rendered explicitly so we can fetch one fresh token per file.
// Without a site key (local development) the check is skipped.

export const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || "";

type Turnstile = {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  reset: (id: string) => void;
};

declare global {
  interface Window { turnstile?: Turnstile }
}

let widgetId: string | null = null;
let waiting: ((token: string) => void)[] = [];
let latest: string | null = null;

export function mountTurnstile(el: HTMLElement) {
  if (!TURNSTILE_SITE_KEY || widgetId || !window.turnstile) return;
  widgetId = window.turnstile.render(el, {
    sitekey: TURNSTILE_SITE_KEY,
    callback: (token: string) => {
      latest = token;
      waiting.forEach((resolve) => resolve(token));
      waiting = [];
    },
  });
}

export function unmountTurnstile() {
  widgetId = null;
  latest = null;
}

/** A single-use token for the next upload ("" when Turnstile is off). */
export async function nextToken(): Promise<string> {
  if (!TURNSTILE_SITE_KEY) return "";
  if (latest) {
    const t = latest;
    latest = null;
    if (widgetId && window.turnstile) window.turnstile.reset(widgetId); // prepare the next one
    return t;
  }
  return new Promise((resolve) => waiting.push((t) => {
    latest = null;
    if (widgetId && window.turnstile) window.turnstile.reset(widgetId);
    resolve(t);
  }));
}
