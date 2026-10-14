# Run Papers Please locally (Windows)

Everything runs on this laptop: no internet and no accounts needed once setup is done.
The demo has its own database in `data\demo\`, so your dev data is never touched.

Open **PowerShell** in the project folder:

```powershell
cd C:\Users\Prabhat\Desktop\Papers-Please
```

---

## 1. One-time setup (skip if it already works)

Only needed on a fresh machine, or if `.venv` or `web\node_modules` is missing.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
npm --prefix web install
tesseract --version
```

The last line must print a version. If it says "not recognized", see [Tesseract missing](#tesseract-missing).

The papers come from `data\raw\` (not in git). Make sure that folder has the PDFs.

## 2. Prepare (once, about 3 minutes)

```powershell
.venv\Scripts\python scripts\demo.py prepare
```

It seeds the demo database from `data\raw` through the real upload checks, builds the website, and saves a snapshot. It ends with `Ready.` and should report `now: {'approved': 14, 'review': 4}`: four subjects (BCS304, BCS501, BCS502, BCS515D), plus four duplicate copies held for review.

It also creates **Desktop\Papers Please Demo**:

| Folder | What's in it |
|---|---|
| `BCS304`, `BCS501`, `BCS502`, `BCS515D` | every paper of that subject, renamed by session (e.g. `JAN 2025 BCS502.pdf`) |
| `Upload during the demo` | the four files to drag into the upload page live |

## 3. Start (right before the demo)

```powershell
.venv\Scripts\python scripts\demo.py start
```

Wait about 30 seconds for the box that says **Papers Please demo is running**. Leave this window open.

| What | URL |
|---|---|
| Home | http://localhost:3000 |
| A subject | http://localhost:3000/s/BCS502 (also `/s/BCS304`, `/s/BCS501`, `/s/BCS515D`) |
| Upload | http://localhost:3000/upload |
| Moderation | http://localhost:3000/admin |
| API health | http://localhost:8000/healthz |
| API docs | http://localhost:8000/api/docs |

**Moderator token:** `papers-please-demo`

What to upload from `Desktop\Papers Please Demo\Upload during the demo\`:

| File | What happens |
|---|---|
| `JUL 2025 BCS502.pdf` | confirm it, it goes live, BCS502 goes from 3 to 4 papers |
| `JAN 2025 BCS502 second scan.pdf` | confirm it, it goes to review (we already have that exam) |
| `lab-notes.pdf` | rejected, not a question paper |
| `locked.pdf` | rejected, password-protected |

The full demo script is in [`docs/DEMO.md`](docs/DEMO.md).

## 4. Stop

Press **Ctrl+C** in the window running `start`. That stops both the website and the API.

If you closed that window and the servers are still running:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 3000,8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

## 5. Reset (between rehearsals)

Puts the database back to how `prepare` left it (removes anything you uploaded). Stop the demo first.

```powershell
.venv\Scripts\python scripts\demo.py reset
.venv\Scripts\python scripts\demo.py start
```

---

## Troubleshooting

### "Port(s) 3000, 8000 already in use"

An old server is still running. Stop it with the `Stop-Process` line from [Stop](#4-stop), then run `start` again. To see what holds a port:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 3000,8000 | ForEach-Object { Get-Process -Id $_.OwningProcess }
```

### "Run `prepare` first", or pages look old or broken

The website build is missing or stale. Rebuild everything:

```powershell
Remove-Item -Recurse -Force web\.next -ErrorAction SilentlyContinue
.venv\Scripts\python scripts\demo.py prepare
```

If only one page shows old data, refresh it once in the browser. `start` refreshes every page when it launches.

### Tesseract missing

Scanned papers need Tesseract OCR. Without it, scans are rejected or come out empty.

```powershell
winget install -e --id UB-Mannheim.TesseractOCR
$env:Path += ";C:\Program Files\Tesseract-OCR"
tesseract --version
```

To keep it on the PATH for new windows, add `C:\Program Files\Tesseract-OCR` under Settings → System → About → Advanced system settings → Environment Variables → Path. Then run `prepare` again.

### The build fails

Run it on its own to see the error:

```powershell
npm --prefix web run build
```

The fonts are stored in `web\src\app\fonts\`, so the build doesn't need the internet. If it complains about missing modules, run `npm --prefix web install` and try again.

### An upload sits on "Read safely" for more than 2 minutes

Look at the `start` window for errors. It's usually a very large scan. Move on to the next file.

### Everything is broken

```powershell
.venv\Scripts\python scripts\demo.py prepare
```

This rebuilds the demo from scratch in about 3 minutes.
