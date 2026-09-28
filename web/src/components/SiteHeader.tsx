"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "./ThemeToggle";
import { UploadIcon } from "./Icons";

const NAV = [
  { href: "/", label: "Subjects", match: (p: string) => p === "/" || p.startsWith("/s/") },
  { href: "/upload", label: "Upload a paper", match: (p: string) => p.startsWith("/upload") },
  { href: "/how-it-works", label: "How ranking works", match: (p: string) => p.startsWith("/how-it-works") },
];

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-3 text-ink no-underline">
      <span className="flex h-[30px] w-[30px] -rotate-6 items-center justify-center rounded-md border-2 border-stamp font-mono text-xs font-medium text-stamp">
        PP
      </span>
      <span className="font-display text-[23px] font-semibold">Papers Please</span>
    </Link>
  );
}

export function SiteHeader() {
  const path = usePathname();
  if (path.startsWith("/admin")) return null;
  return (
    <header data-site-header className="border-b border-line">
      <div className="mx-auto flex h-[72px] max-w-[1440px] items-center gap-11 px-20">
        <Logo />
        <nav aria-label="Main" className="flex gap-7 text-[15px]">
          {NAV.map((item) => {
            const active = item.match(path);
            return (
              <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined}
                className={active
                  ? "border-b-2 border-ink pb-1 font-semibold text-ink"
                  : "pb-1.5 text-ink-2 hover:text-ink"}>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex-grow" />
        <ThemeToggle />
        {!path.startsWith("/upload") && (
          <Link href="/upload"
            className="flex h-11 items-center gap-2 rounded-[10px] bg-ink px-[18px] text-[15px] font-medium text-inverse hover:opacity-90">
            <UploadIcon size={18} /> Upload a paper
          </Link>
        )}
      </div>
    </header>
  );
}
