import { revalidatePath } from "next/cache";
import type { NextRequest } from "next/server";

/**
 * Called by the API server right after a subject is republished, so the
 * affected pages refresh on their next visit instead of waiting for the timer.
 */
export async function POST(req: NextRequest) {
  const secret = process.env.REVALIDATE_SECRET;
  if (!secret || req.headers.get("authorization") !== `Bearer ${secret}`) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const body = (await req.json().catch(() => ({}))) as { paths?: unknown };
  const paths = Array.isArray(body.paths) ? body.paths : [];
  const done: string[] = [];
  for (const p of paths.slice(0, 20)) {
    if (typeof p === "string" && /^\/[A-Za-z0-9/_-]{0,64}$/.test(p)) {
      revalidatePath(p);
      done.push(p);
    }
  }
  return Response.json({ revalidated: done });
}
