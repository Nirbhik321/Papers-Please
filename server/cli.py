"""
cli.py — seed and maintain the database from the command line.

  python -m server.cli seed data/raw        import every PDF in a folder
  python -m server.cli rebuild [CODE ...]   republish subjects (all if none given)
  python -m server.cli status               paper counts by status

Seeding goes through exactly the same checks as a student upload: extraction in
the sandbox, detected metadata used as the confirmation, duplicates held for
review. Files whose subject can't be detected are left waiting for confirmation.
"""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from server import ingest
from server.db import engine, init_db, papers
from server.worker import worker


def seed(folder: str) -> None:
    files = sorted(Path(folder).glob("*.pdf"))
    print(f"Seeding {len(files)} PDFs from {folder}")
    for path in files:
        try:
            pid, _ = ingest.create_upload(path.read_bytes(), path.name, uploader_hash="seed")
        except ingest.DuplicateUpload as dup:
            print(f"  = {path.name}: already in the bank (#{dup.paper['id']}, {dup.paper['status']})")
            continue
        worker.process(pid)
        worker.drain()
        paper = ingest.get_paper(pid)
        if paper["status"] == "awaiting_confirmation":
            d = json.loads(paper["detected"])
            if not d["subjectCode"]:
                print(f"  ? {path.name}: subject not detected - confirm it in the moderation page (#{pid})")
                continue
            try:
                ingest.confirm_paper(pid, d["subjectCode"], d["examYear"], d["examMonth"], d["paperType"])
            except ingest.ActionError as e:
                print(f"  ? {path.name}: {e} - confirm it in the moderation page (#{pid})")
                continue
            worker.match(pid)
            worker.drain()
            paper = ingest.get_paper(pid)
        mark = {"approved": "+", "review": "!", "rejected": "x"}.get(paper["status"], "?")
        reason = f" - {paper['status_reason']}" if paper["status_reason"] else ""
        print(f"  {mark} {path.name}: {paper['status']} {paper['subject_code'] or ''}{reason}")


def rebuild(codes: list[str]) -> None:
    if not codes:
        with engine.connect() as conn:
            codes = [r[0] for r in conn.execute(
                select(papers.c.subject_code).where(papers.c.status == "approved").distinct())]
    for code in codes:
        print(f"  rebuilding {code.upper()}")
        worker.publish(code.upper())
    worker.drain()


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m server.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed").add_argument("folder")
    sub.add_parser("rebuild").add_argument("codes", nargs="*")
    sub.add_parser("status")
    args = ap.parse_args()

    init_db()
    if args.cmd == "seed":
        seed(args.folder)
    elif args.cmd == "rebuild":
        rebuild(args.codes)
    elif args.cmd == "status":
        for status, n in sorted(ingest.counts().items()):
            print(f"  {status:<22} {n}")


if __name__ == "__main__":
    main()
