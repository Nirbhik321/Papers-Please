"""
worker.py — one background thread that does all the heavy work, one job at a time.

Running jobs one at a time keeps memory flat on a 512 MB server: at most one
PDF is being read and one subject rebuilt at any moment. Jobs are cheap to
lose — on startup, every paper still marked 'processing' is simply queued again.
"""

import logging
import queue
import threading
import traceback

from sqlalchemy import select

from server import ingest
from server.db import engine, papers

log = logging.getLogger("papers.worker")


class Worker:
    def __init__(self):
        self.jobs: queue.Queue = queue.Queue()
        self._pending_publish: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ── Queueing ───────────────────────────────────────────────────────────────
    def process(self, pid: int) -> None:
        self.jobs.put(("process", pid))

    def match(self, pid: int) -> None:
        self.jobs.put(("match", pid))

    def publish(self, code: str, pid: int | None = None) -> None:
        with self._lock:   # collapse repeated rebuilds of the same subject
            if code in self._pending_publish and pid is None:
                return
            self._pending_publish.add(code)
        self.jobs.put(("publish", (pid, code)))

    # ── Running ────────────────────────────────────────────────────────────────
    def run_one(self, job) -> None:
        kind, arg = job
        try:
            if kind == "process":
                ingest.process_paper(arg)
            elif kind == "match":
                ingest.match_paper(arg)
            elif kind == "publish":
                pid, code = arg
                with self._lock:
                    self._pending_publish.discard(code)
                ingest.publish(pid, code)
        except Exception as e:
            log.error("job %s failed: %s\n%s", job, e, traceback.format_exc())
            if kind in ("process", "match"):
                ingest._set(arg, status="failed", stage="done",
                            status_reason="Something went wrong on our side. A moderator will retry it.")

    def drain(self) -> None:
        """Run every queued job now, in this thread (CLI and tests)."""
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return
            self.run_one(job)

    def _loop(self) -> None:
        while True:
            self.run_one(self.jobs.get())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.resume_unfinished()
        self._thread = threading.Thread(target=self._loop, name="papers-worker", daemon=True)
        self._thread.start()

    def resume_unfinished(self) -> None:
        with engine.connect() as conn:
            rows = conn.execute(select(papers.c.id, papers.c.stage, papers.c.status, papers.c.subject_code)
                                .where(papers.c.status.in_(["processing", "approved"]))
                                .where(papers.c.stage != "done")).all()
        for r in rows:
            if r.status == "approved":
                self.publish(r.subject_code, r.id)
            elif r.stage == "matching":
                self.match(r.id)
            else:
                self.process(r.id)


worker = Worker()
