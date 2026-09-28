"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto flex max-w-[1440px] flex-col items-start gap-5 px-20 pt-24">
      <h1 className="font-display text-5xl font-semibold">The question bank is waking up.</h1>
      <p className="max-w-[620px] text-lg text-ink-2">
        We couldn&apos;t reach our server just now. It usually answers within a few seconds — try again.
      </p>
      <button type="button" onClick={reset}
        className="h-12 cursor-pointer rounded-xl bg-ink px-5 font-semibold text-inverse">
        Try again
      </button>
    </main>
  );
}
