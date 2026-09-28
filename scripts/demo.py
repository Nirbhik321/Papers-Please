"""
demo.py — run Papers Please locally for a demo, on its own database.

  .venv\\Scripts\\python scripts\\demo.py prepare   build the demo database + production site (≈5 min, once)
  .venv\\Scripts\\python scripts\\demo.py start     start the API and the site; Ctrl+C stops both
  .venv\\Scripts\\python scripts\\demo.py reset     put the demo database back to how `prepare` left it

Everything lives in data/demo/ — your normal dev data (data/app.db) is untouched.

`prepare` seeds every paper in data/raw EXCEPT the ones held back for the live part
of the demo, which it copies to data/demo/live-upload/ along with two junk files:
  july 2025 BCS502.pdf     → upload it: goes live, BCS502 goes from 3 to 4 papers
  DecJan_2025_…CN….pdf     → upload it: a re-scan of an exam we have → held for review
  lab-notes.pdf            → upload it: not a question paper → rejected
  locked.pdf               → upload it: password-protected → rejected
"""

import argparse
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # box-drawing output on any Windows console

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
DB = DEMO / "demo.db"
STORAGE = DEMO / "storage"
SNAPSHOT = DEMO / "snapshot"
LIVE = DEMO / "live-upload"
RAW = ROOT / "data" / "raw"
PY = sys.executable

API_PORT, WEB_PORT = 8000, 3000
ADMIN_TOKEN = os.environ.get("DEMO_ADMIN_TOKEN", "papers-please-demo")
REVALIDATE_SECRET = "papers-please-demo-revalidate"

HELD_BACK = ["july 2025 BCS502.pdf", "DecJan_2025_-_Scheme  CN-1-2.pdf"]

# Scanned papers whose code isn't readable: confirmed as the CSE subjects for the demo
CONFIRM = {
    "DS JUNE JULY 25.pdf": ("BCS515D", 2025, "July", "see"),
    "JuneJuly_2025.pdf": ("BCS501", 2025, "July", "see"),
    "BCS515D.pdf": ("BCS515D", None, None, "model"),
    "MQP 2.pdf": ("BCS502", None, None, "model"),
}


def api_env() -> dict:
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": f"sqlite:///{DB.as_posix()}",
        "STORAGE_DIR": str(STORAGE),
        "ADMIN_TOKEN": ADMIN_TOKEN,
        "UPLOADS_PER_HOUR": "500",
        "TURNSTILE_SECRET_KEY": "",
        "SUPABASE_URL": "",
        "CORS_ORIGINS": f"http://localhost:{WEB_PORT}",
        "SITE_URL": f"http://localhost:{WEB_PORT}",
        "REVALIDATE_URL": f"http://localhost:{WEB_PORT}/api/revalidate",
        "REVALIDATE_SECRET": REVALIDATE_SECRET,
        "HF_HUB_OFFLINE": "1",            # the embedding model is cached; never wait on the network
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def web_env() -> dict:
    env = dict(os.environ)
    env.update({
        "NEXT_PUBLIC_API_URL": f"http://localhost:{API_PORT}",
        "API_URL": f"http://localhost:{API_PORT}",
        "REVALIDATE_SECRET": REVALIDATE_SECRET,
        "NEXT_PUBLIC_TURNSTILE_SITE_KEY": "",
        "NEXT_PUBLIC_SUPABASE_URL": "",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY": "",
        "NEXT_TELEMETRY_DISABLED": "1",
    })
    return env


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise SystemExit(f"Timed out waiting for {url}")


def start_api() -> subprocess.Popen:
    return subprocess.Popen(
        [PY, "-m", "uvicorn", "server.main:app", "--port", str(API_PORT), "--log-level", "warning"],
        cwd=ROOT, env=api_env())


def npm(*args) -> list[str]:
    return ["npm.cmd" if os.name == "nt" else "npm", "--prefix", str(ROOT / "web"), *args]


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":   # kill the whole tree (npm → node)
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def ensure_ports_free() -> None:
    busy = [p for p in (API_PORT, WEB_PORT) if port_busy(p)]
    if busy:
        raise SystemExit(f"Port(s) {', '.join(map(str, busy))} already in use — stop whatever is running there "
                         "(an old dev server?) and try again.")


def run_py(code: str) -> None:
    subprocess.run([PY, "-W", "ignore", "-c", code], cwd=ROOT, env=api_env(), check=True)


def make_junk_files() -> None:
    import pymupdf
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((72, 90), f"Lab record — week {i + 1}", fontsize=16)
        page.insert_text((72, 130), "Experiment: configure a static route between two routers.")
    doc.save(str(LIVE / "lab-notes.pdf"))

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 90), "Confidential", fontsize=16)
    buf = io.BytesIO()
    doc.save(buf, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    (LIVE / "locked.pdf").write_bytes(buf.getvalue())


def prepare() -> None:
    ensure_ports_free()
    if DEMO.exists():
        shutil.rmtree(DEMO)
    (DEMO / "seed").mkdir(parents=True)
    LIVE.mkdir(parents=True)

    for pdf in sorted(RAW.glob("*.pdf")):
        target = LIVE if pdf.name in HELD_BACK else DEMO / "seed"
        shutil.copy2(pdf, target / pdf.name)
    make_junk_files()

    print("1/4  Seeding the demo database (every paper goes through the normal checks)…")
    subprocess.run([PY, "-W", "ignore", "-m", "server.cli", "seed", str(DEMO / "seed")],
                   cwd=ROOT, env=api_env(), check=True)

    print("2/4  Confirming papers whose subject or year couldn't be read…")
    run_py(f"""
import json
from sqlalchemy import select
from server import ingest
from server.db import engine, papers
from server.worker import worker
confirm = {CONFIRM!r}
with engine.connect() as c:
    waiting = c.execute(select(papers.c.id, papers.c.filename).where(papers.c.status == 'awaiting_confirmation')).all()
for pid, name in waiting:
    if name in confirm:
        code, year, month, kind = confirm[name]
        ingest.confirm_paper(pid, code, year, month, kind)
        worker.match(pid); worker.drain()
        p = ingest.get_paper(pid)
        print(f"     {{name}}: {{p['status']}} {{p['status_reason'] or ''}}")
    else:
        print(f"     {{name}}: left for the moderation page")
print("     now:", ingest.counts())
""")

    print("3/4  Building the site in production mode (the API runs so pages are pre-rendered with data)…")
    api = start_api()
    try:
        wait_for(f"http://localhost:{API_PORT}/healthz")
        subprocess.run(npm("run", "build"), env=web_env(), check=True)
    finally:
        stop(api)

    print("4/4  Saving a snapshot for `reset`…")
    if SNAPSHOT.exists():
        shutil.rmtree(SNAPSHOT)
    SNAPSHOT.mkdir()
    for f in DEMO.glob("demo.db*"):
        shutil.copy2(f, SNAPSHOT / f.name)
    shutil.copytree(STORAGE, SNAPSHOT / "storage")
    shutil.rmtree(DEMO / "seed")
    print(f"\nReady. Start it with:  {Path(PY).name} scripts/demo.py start")


def reset() -> None:
    if not SNAPSHOT.exists():
        raise SystemExit("No snapshot yet — run `prepare` first.")
    if port_busy(API_PORT):
        raise SystemExit("Stop the running demo (Ctrl+C in its window) before resetting.")
    for f in DEMO.glob("demo.db*"):
        f.unlink()
    for f in SNAPSHOT.glob("demo.db*"):
        shutil.copy2(f, DEMO / f.name)
    shutil.rmtree(STORAGE, ignore_errors=True)
    shutil.copytree(SNAPSHOT / "storage", STORAGE)
    print("Demo data reset. The site refreshes its pages the next time you run `start`.")


def refresh_site() -> None:
    """After a reset or a rehearsal, make sure no page shows stale data."""
    with urllib.request.urlopen(f"http://localhost:{API_PORT}/api/subjects", timeout=10) as r:
        codes = [s["code"] for s in json.load(r)]
    paths = ["/"] + [f"/s/{c}" for c in codes]
    req = urllib.request.Request(
        f"http://localhost:{WEB_PORT}/api/revalidate", method="POST",
        data=json.dumps({"paths": paths}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {REVALIDATE_SECRET}"})
    urllib.request.urlopen(req, timeout=10).read()
    for _ in range(2):   # regenerate each page so the first visitor never waits or sees old data
        for p in paths:
            try:
                urllib.request.urlopen(f"http://localhost:{WEB_PORT}{p}", timeout=60).read()
            except Exception:
                pass


def start() -> None:
    if not (ROOT / "web" / ".next" / "BUILD_ID").exists() or not DB.exists():
        raise SystemExit("Run `prepare` first.")
    ensure_ports_free()
    api = start_api()
    web = subprocess.Popen(npm("run", "start", "--", "-p", str(WEB_PORT)), env=web_env())
    try:
        wait_for(f"http://localhost:{API_PORT}/healthz")
        wait_for(f"http://localhost:{WEB_PORT}/how-it-works")
        refresh_site()
        print(f"""
  ┌───────────────────────────────────────────────────────────────┐
  │  Papers Please demo is running                                 │
  │                                                                │
  │  Website      http://localhost:{WEB_PORT}                             │
  │  Moderation   http://localhost:{WEB_PORT}/admin                       │
  │               token: {ADMIN_TOKEN:<42}│
  │  API docs     http://localhost:{API_PORT}/api/docs                    │
  │                                                                │
  │  Files for the live upload: data\\demo\\live-upload\\             │
  │  Ctrl+C stops everything.                                      │
  └───────────────────────────────────────────────────────────────┘
""")
        while api.poll() is None and web.poll() is None:
            time.sleep(1)
        print("A server exited — stopping the demo.")
    except KeyboardInterrupt:
        pass
    finally:
        stop(web)
        stop(api)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python scripts/demo.py")
    ap.add_argument("command", choices=["prepare", "start", "reset"])
    {"prepare": prepare, "start": start, "reset": reset}[ap.parse_args().command]()


if __name__ == "__main__":
    main()
