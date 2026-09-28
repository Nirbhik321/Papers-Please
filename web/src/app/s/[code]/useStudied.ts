"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Topics a student has ticked as studied, kept in this browser only
 * (no account needed). Keyed by the topic's stable key, which survives
 * the subject being republished when new papers arrive.
 */
export function useStudied(code: string) {
  const storageKey = `studied:${code}`;
  const [studied, setStudied] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- loading browser-only state after hydration
      if (raw) setStudied(new Set(JSON.parse(raw) as string[]));
    } catch {}
  }, [storageKey]);

  const toggle = useCallback((key: string) => {
    setStudied((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      try {
        localStorage.setItem(storageKey, JSON.stringify([...next]));
      } catch {}
      return next;
    });
  }, [storageKey]);

  return { studied, toggle };
}
