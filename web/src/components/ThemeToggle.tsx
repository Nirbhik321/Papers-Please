"use client";

import { MoonIcon, SunIcon } from "./Icons";

/** Inline script run before first paint so the page never flashes the wrong theme. */
export const themeScript = `(function(){try{var t=localStorage.getItem("theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t}catch(e){}})()`;

export function ThemeToggle() {
  function toggle() {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {}
  }
  return (
    <button type="button" onClick={toggle} aria-label="Toggle dark mode"
      className="flex h-11 w-11 items-center justify-center rounded-[10px] border border-line text-ink hover:bg-surface cursor-pointer">
      <span className="dark:hidden"><MoonIcon /></span>
      <span className="hidden dark:inline"><SunIcon /></span>
    </button>
  );
}
