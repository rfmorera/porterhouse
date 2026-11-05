from collections import defaultdict
from typing import Callable, Optional

from porterhouse.api_client import ApiError
from porterhouse.dtos import (
    Balance,
    ItemBalances,
    ItemPlan,
    PendingRevision,
    SyncPlan,
    SyncReport,
)
from porterhouse.rates import RateUnavailable
from porterhouse.workbook_reader import SheetNotFound

AMOUNT_TOLERANCE = 0.005
ABORT_STATUSES = {401, 403}


class SyncService:

    def __init__(self, specs: list, rates, ledger, log: Callable[[str], None]):
        self.specs = specs
        self.rates = rates
        self.ledger = ledger
        self.log = log

    def plan(self, reader) -> SyncPlan:
        warnings = []
        items = []
        for spec in self.specs:
            try:
                records, sheet_warnings = reader.read(spec.sheet)
            except SheetNotFound:
                warnings.append(f"[{spec.sheet}] la hoja no existe en el archivo, omitida")
                self.log(f"[aviso] hoja '{spec.sheet}' no está en el archivo, omitida")
                continue
            for warning in sheet_warnings:
                self.log(f"[aviso] {warning}")
            warnings.extend(sheet_warnings)
            built = _build_items(spec, records, warnings, self.log)
            self.log(
                f"Hoja '{spec.sheet}': {len(records)} filas válidas, "
                f"{len(built)} ítem(s), {len(sheet_warnings)} aviso(s)"
            )
            items.extend(built)
        for item in items:
            self._convert(item, warnings)
        plans = [self._diff(item) for item in items]
        return SyncPlan(items=plans, warnings=warnings)

    def apply(self, plan: SyncPlan, client, dry_run: bool) -> SyncReport:
        report = SyncReport(warnings=len(plan.warnings))
        remote_by_name = None
        for item_plan in plan.items:
            name = item_plan.item.name
            if not item_plan.pending:
                self.log(f"{name}: sin cambios")
                continue
            label = "nuevo" if item_plan.is_new else "existente"
            self.log(f"{name} ({label}): {len(item_plan.pending)} revisión(es) por enviar")
            if dry_run:
                for pending in item_plan.pending:
                    self.log(f"  {_describe(pending)}")
                report.revisions_skipped += len(item_plan.pending)
                continue
            try:
                if item_plan.is_new:
                    if remote_by_name is None:
                        remote_by_name = _remote_by_name(client)
                    self._ensure_item(item_plan, remote_by_name, client, report)
                self._send_revisions(item_plan, client, report)
            except ApiError as error:
                message = f"[error] {name}: {error}"
                self.log(message)
                report.errors.append(message)
                if error.status in ABORT_STATUSES:
                    self.log("[error] token inválido o feature NET_WORTH no habilitada, se detiene el envío")
                    break
        return report

    def _ensure_item(self, item_plan: ItemPlan, remote_by_name: dict, client, report):
        item = item_plan.item
        spec = item.spec
        remote = remote_by_name.get(spec.name.lower())
        if remote:
            self.log(f"  ya existe en la API como id {remote['id']}, se reutiliza")
            item_plan.existing = self.ledger.register_item(
                item.key, remote["id"], spec.name, spec.account_type, spec.subtype
            )
            report.items_reused += 1
            return
        first = item_plan.pending.pop(0)
        payload = {
            "name": spec.name,
            "type": spec.account_type,
            "subtype": spec.subtype,
            "amount": first.balance.amount_usd,
            "note": spec.note[:120],
            "icon": spec.icon,
            "date": first.balance.day,
        }
        created = client.create_manual_item(payload)
        item_plan.existing = self.ledger.register_item(
            item.key, created["id"], spec.name, spec.account_type, spec.subtype
        )
        self.ledger.record_revision(
            item.key,
            first.balance.day,
            first.balance.amount_usd,
            first.balance.original_amount,
            first.balance.currency,
            first.balance.rate,
        )
        report.items_created += 1
        report.revisions_sent += 1
        self.log(f"  creado con id {created['id']} ({_describe(first)})")

    def _send_revisions(self, item_plan: ItemPlan, client, report):
        item = item_plan.item
        total = len(item_plan.pending)
        for index, pending in enumerate(item_plan.pending, start=1):
            client.update_manual_item(
                item_plan.existing.item_id,
                {"amount": pending.balance.amount_usd, "date": pending.balance.day},
            )
            self.ledger.record_revision(
                item.key,
                pending.balance.day,
                pending.balance.amount_usd,
                pending.balance.original_amount,
                pending.balance.currency,
                pending.balance.rate,
            )
            report.revisions_sent += 1
            self.log(f"  [{index}/{total}] {_describe(pending)}")

    def _convert(self, item: ItemBalances, warnings: list):
        kept = []
        converted = 0
        total = len(item.balances)
        for balance in item.balances:
            if balance.currency == "UYU":
                try:
                    quote = self.rates.uyu_per_usd(balance.day)
                except RateUnavailable as error:
                    message = (
                        f"[{item.spec.sheet}] {balance.day}: sin cotización UYU/USD ({error}), "
                        "queda pendiente para la próxima corrida"
                    )
                    warnings.append(message)
                    self.log(f"[aviso] {message}")
                    continue
                balance.rate = quote.rate
                balance.rate_source = quote.source
                balance.amount_usd = round(balance.original_amount / quote.rate, 2)
                converted += 1
            else:
                balance.amount_usd = round(balance.original_amount, 2)
            if balance.amount_usd < 0:
                message = (
                    f"[{item.spec.sheet}] {balance.day}: saldo negativo "
                    f"{balance.amount_usd} USD, se envía 0 (la API no acepta negativos)"
                )
                warnings.append(message)
                self.log(f"[aviso] {message}")
                balance.amount_usd = 0.0
            kept.append(balance)
        item.balances = kept
        if converted:
            self.log(f"{item.name}: {converted} saldo(s) convertidos de UYU a USD")
        if total and not kept:
            message = (
                f"{item.name}: ninguno de sus {total} saldos tiene cotización, "
                "el ítem no se crea ni se actualiza hasta resolver la cotización UYU/USD"
            )
            warnings.append(message)
            self.log(f"[aviso] {message}")

    def _diff(self, item: ItemBalances) -> ItemPlan:
        existing = self.ledger.get(item.key)
        pending = []
        for balance in sorted(item.balances, key=lambda entry: entry.day):
            previous = existing.revisions.get(balance.day) if existing else None
            if previous is None:
                pending.append(PendingRevision(balance, "nueva"))
            elif abs(previous.amount - balance.amount_usd) >= AMOUNT_TOLERANCE:
                pending.append(
                    PendingRevision(balance, f"cambió de {previous.amount:.2f} USD")
                )
        return ItemPlan(item=item, existing=existing, pending=pending)


def _build_items(spec, records: list, warnings: list, log) -> list:
    if spec.mode == "cumulative":
        grouped = defaultdict(list)
        for record in records:
            grouped[record.nombre].append(record)
        return [
            _cumulative_item(spec.for_name(nombre), f"{spec.sheet}::{nombre}", rows)
            for nombre, rows in grouped.items()
        ]
    return [_balance_item(spec, f"{spec.sheet}::{spec.name}", records, warnings, log)]


def _balance_item(spec, key: str, records: list, warnings: list, log) -> ItemBalances:
    by_day = {}
    for record in records:
        if record.day in by_day:
            message = (
                f"[{spec.sheet}] fila {record.row}: repite la fecha {record.day} "
                f"de la fila {by_day[record.day].rows[-1]}, se usa la última"
            )
            warnings.append(message)
            log(f"[aviso] {message}")
        by_day[record.day] = Balance(
            day=record.day,
            original_amount=record.amount,
            currency=spec.currency,
            rows=[record.row],
        )
    return ItemBalances(key=key, spec=spec, balances=list(by_day.values()))


def _cumulative_item(spec, key: str, records: list) -> ItemBalances:
    total = 0.0
    by_day = {}
    for record in sorted(records, key=lambda entry: (entry.day, entry.row)):
        total = round(total + record.amount, 2)
        if record.day in by_day:
            by_day[record.day].original_amount = total
            by_day[record.day].rows.append(record.row)
        else:
            by_day[record.day] = Balance(
                day=record.day,
                original_amount=total,
                currency=spec.currency,
                rows=[record.row],
            )
    return ItemBalances(key=key, spec=spec, balances=list(by_day.values()))


def _remote_by_name(client) -> dict:
    return {
        (item.get("name") or "").strip().lower(): item
        for item in client.list_manual_items()
        if item.get("id")
    }


def _describe(pending: PendingRevision) -> str:
    balance = pending.balance
    if balance.currency == "UYU":
        return (
            f"{balance.day}: {balance.amount_usd:.2f} USD "
            f"({balance.original_amount:.2f} UYU a {balance.rate} {balance.rate_source}) [{pending.reason}]"
        )
    return f"{balance.day}: {balance.amount_usd:.2f} USD [{pending.reason}]"
