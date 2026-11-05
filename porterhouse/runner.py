from datetime import date
from pathlib import Path
from typing import Callable, Optional

from porterhouse.api_client import MondayCallClient
from porterhouse.config import Settings, resolve_environment
from porterhouse.dtos import SyncReport
from porterhouse.ledger import Ledger
from porterhouse.rates import RateService
from porterhouse.sheet_specs import load_sheet_config
from porterhouse.sync_service import SyncService
from porterhouse.workbook_reader import WorkbookReader


class MissingToken(Exception):
    pass


def run_sync(
    workbook_path: Path,
    settings: Settings,
    log: Callable[[str], None],
    token: str = "",
    dry_run: bool = False,
    rate_override: Optional[float] = None,
    today: Optional[date] = None,
    environment: str = "",
) -> SyncReport:
    environment = resolve_environment(environment or settings.environment)
    api_url = settings.api_url_for(environment)
    ledger_path = settings.ledger_path_for(environment)
    token = (token or settings.jwt).strip()
    if not token and not dry_run:
        raise MissingToken(
            "Falta el JWT: definí MONDAYCALL_JWT en el entorno o pasalo en el formulario"
        )
    specs, ignored = load_sheet_config(settings.sheets_path)
    reader = WorkbookReader(workbook_path, today or date.today())
    log(f"Archivo: {Path(workbook_path).name} ({len(reader.sheet_names)} hojas)")
    mapped = {spec.sheet for spec in specs}
    skipped = [name for name in reader.sheet_names if name in ignored]
    if skipped:
        log(f"Hojas excluidas por sheets.json: {', '.join(skipped)}")
    unknown = [name for name in reader.sheet_names if name not in mapped and name not in ignored]
    if unknown:
        log(f"[aviso] hojas sin mapeo en sheets.json, ignoradas: {', '.join(unknown)}")
    log(f"Entorno: {environment} ({api_url})")
    ledger = Ledger(ledger_path)
    log(f"Registro local: {ledger_path.name} ({len(ledger.items)} ítem(s) ya enviados)")
    rates = RateService(settings.rates_path, override=rate_override)
    service = SyncService(specs, rates, ledger, log)
    plan = service.plan(reader)
    if rates.fetched:
        log(f"Cotizaciones UYU/USD descargadas: {rates.fetched} (guardadas en {settings.rates_path.name})")
    log(f"Revisiones pendientes de envío: {plan.pending_count}")
    client = None
    if not dry_run:
        client = MondayCallClient(api_url, token)
    else:
        log("Modo simulación: no se envía nada a la API")
    report = service.apply(plan, client, dry_run)
    log(
        f"Listo. Ítems creados: {report.items_created}, reutilizados: {report.items_reused}, "
        f"revisiones enviadas: {report.revisions_sent}, simuladas: {report.revisions_skipped}, "
        f"avisos: {report.warnings}, errores: {len(report.errors)}"
    )
    return report
