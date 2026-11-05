import queue
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from porterhouse.config import ENVIRONMENTS, ROOT, load_settings, resolve_environment
from porterhouse.ledger import Ledger
from porterhouse.rates import GOOGLE_RATES_CSV_URL
from porterhouse.runner import MissingToken, run_sync

app = FastAPI(title="porterhouse")
WEB_DIR = ROOT / "web"
DONE = object()
_running = threading.Lock()


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/status")
def status():
    settings = load_settings()
    environments = {}
    for name in ENVIRONMENTS:
        ledger = Ledger(settings.ledger_path_for(name))
        environments[name] = {
            "api_url": settings.api_url_for(name),
            "ledger_items": len(ledger.items),
            "ledger_revisions": sum(len(item.revisions) for item in ledger.items.values()),
        }
    return {
        "default_environment": settings.environment,
        "environments": environments,
        "has_env_token": settings.has_token,
        "has_google_rates": bool(GOOGLE_RATES_CSV_URL),
    }


@app.post("/api/sync")
async def sync(
    file: UploadFile = File(...),
    token: str = Form(""),
    dry_run: bool = Form(False),
    rate: Optional[str] = Form(None),
    environment: str = Form(""),
):
    try:
        environment = resolve_environment(environment or load_settings().environment)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if not _running.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ya hay una sincronización en curso")
    workdir = Path(tempfile.mkdtemp(prefix="porterhouse-"))
    workbook = workdir / (Path(file.filename or "book.xlsx").name or "book.xlsx")
    with workbook.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    rate_override = float(rate) if rate else None
    lines: queue.Queue = queue.Queue()

    def worker():
        try:
            run_sync(
                workbook,
                load_settings(),
                log=lines.put,
                token=token,
                dry_run=dry_run,
                rate_override=rate_override,
                environment=environment,
            )
        except MissingToken as error:
            lines.put(f"[error] {error}")
        except Exception as error:
            lines.put(f"[error] {type(error).__name__}: {error}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            _running.release()
            lines.put(DONE)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            line = lines.get()
            if line is DONE:
                break
            yield f"{line}\n"

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")
