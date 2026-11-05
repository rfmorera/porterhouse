import json
from datetime import date

import pytest

from porterhouse.api_client import ApiError
from porterhouse.config import Settings, resolve_environment
from porterhouse.dtos import RateQuote
from porterhouse.ledger import Ledger
from porterhouse.rates import RateService
from porterhouse.runner import MissingToken, run_sync
from porterhouse.sheet_specs import load_sheet_specs
from porterhouse.sync_service import SyncService
from porterhouse.workbook_reader import WorkbookReader


class FakeClient:
    def __init__(self, existing=None, fail_status=None):
        self.existing = existing or []
        self.created = []
        self.updated = []
        self.fail_status = fail_status
        self._next = 1

    def list_manual_items(self):
        return self.existing

    def create_manual_item(self, payload):
        if self.fail_status:
            raise ApiError(self.fail_status, "feature")
        self.created.append(payload)
        item_id = f"id-{self._next}"
        self._next += 1
        return {"id": item_id, **payload}

    def update_manual_item(self, item_id, payload):
        self.updated.append((item_id, payload))
        return {"id": item_id, **payload}


def _service(tmp_path, specs_path, log, ledger=None):
    rates = RateService(
        tmp_path / "rates.json",
        fetchers=[lambda day: RateQuote(rate=40.0, source="test", quote_day=day)],
    )
    ledger = ledger or Ledger(tmp_path / "ledger.json")
    return SyncService(load_sheet_specs(specs_path), rates, ledger, log), ledger


def test_plan_builds_balances_cumulatives_and_conversions(tmp_path, workbook_path, specs_path, today):
    lines = []
    service, _ledger = _service(tmp_path, specs_path, lines.append)

    plan = service.plan(WorkbookReader(workbook_path, today))

    by_name = {item.item.name: item for item in plan.items}
    assert set(by_name) == {"Efectivo", "Pesos Rafael", "Inversión Gletir", "Inversión Binance"}
    assert [(p.balance.day, p.balance.amount_usd) for p in by_name["Efectivo"].pending] == [
        ("2022-08-29", 1700.0),
        ("2023-01-07", 1882.0),
        ("2023-02-01", 0.0),
    ]
    assert [(p.balance.day, p.balance.amount_usd, p.balance.rate) for p in by_name["Pesos Rafael"].pending] == [
        ("2023-02-10", 1734.26, 40.0),
        ("2023-03-10", 1000.0, 40.0),
    ]
    assert [(p.balance.day, p.balance.amount_usd) for p in by_name["Inversión Gletir"].pending] == [
        ("2025-03-07", 2000.0),
        ("2025-03-12", 0.0),
    ]
    assert by_name["Inversión Binance"].item.spec.subtype == "crypto exchange"
    assert by_name["Inversión Binance"].item.spec.icon == "crypto"
    assert any("No existe" in warning for warning in plan.warnings)
    assert any("saldo negativo" in warning for warning in plan.warnings)


def test_apply_creates_items_sends_revisions_and_records_them(tmp_path, workbook_path, specs_path, today):
    lines = []
    service, ledger = _service(tmp_path, specs_path, lines.append)
    client = FakeClient(existing=[{"id": "remote-1", "name": "efectivo"}])
    plan = service.plan(WorkbookReader(workbook_path, today))

    report = service.apply(plan, client, dry_run=False)

    assert report.items_reused == 1
    assert report.items_created == 3
    assert report.errors == []
    assert client.created[0]["name"] == "Pesos Rafael"
    assert client.created[0]["date"] == "2023-02-10"
    assert client.created[0]["amount"] == 1734.26
    assert ("remote-1", {"amount": 1700.0, "date": "2022-08-29"}) in client.updated
    saved = json.loads((tmp_path / "ledger.json").read_text())
    assert saved["items"]["Efectivo::Efectivo"]["item_id"] == "remote-1"
    assert saved["items"]["Pesos Rafael::Pesos Rafael"]["revisions"]["2023-03-10"]["rate"] == 40.0
    assert report.revisions_sent == 3 + 2 + 2 + 1

    second_plan = service.plan(WorkbookReader(workbook_path, today))

    assert second_plan.pending_count == 0


def test_a_changed_amount_is_sent_again(tmp_path, workbook_path, specs_path, today):
    lines = []
    service, ledger = _service(tmp_path, specs_path, lines.append)
    client = FakeClient()
    service.apply(service.plan(WorkbookReader(workbook_path, today)), client, dry_run=False)
    ledger.record_revision("Efectivo::Efectivo", "2022-08-29", 1.0, 1.0, "USD", None)

    plan = service.plan(WorkbookReader(workbook_path, today))

    assert [(p.balance.day, p.reason) for item in plan.items for p in item.pending] == [
        ("2022-08-29", "cambió de 1.00 USD")
    ]


def test_dry_run_sends_nothing(tmp_path, workbook_path, specs_path, today):
    lines = []
    service, _ledger = _service(tmp_path, specs_path, lines.append)
    client = FakeClient()

    report = service.apply(service.plan(WorkbookReader(workbook_path, today)), client, dry_run=True)

    assert client.created == [] and client.updated == []
    assert report.revisions_sent == 0
    assert report.revisions_skipped == 8


def test_environment_picks_api_url_and_its_own_ledger(tmp_path, specs_path):
    settings = Settings(
        jwt="",
        environment="dev",
        api_url_override="",
        ledger_dir=tmp_path,
        rates_path=tmp_path / "rates.json",
        sheets_path=specs_path,
    )

    assert settings.api_url_for("dev") == "https://api-dev.moneycall.io"
    assert settings.api_url_for("prod") == "https://api.moneycall.io"
    assert settings.ledger_path_for("prod") == tmp_path / "ledger.prod.json"
    assert resolve_environment("") == "dev"
    assert resolve_environment("PROD") == "prod"
    with pytest.raises(ValueError):
        resolve_environment("staging")


def test_forbidden_stops_the_run(tmp_path, workbook_path, specs_path, today):
    lines = []
    service, _ledger = _service(tmp_path, specs_path, lines.append)
    client = FakeClient(fail_status=403)

    report = service.apply(service.plan(WorkbookReader(workbook_path, today)), client, dry_run=False)

    assert len(report.errors) == 1
    assert client.updated == []


def test_runner_requires_a_token_unless_dry_run(tmp_path, workbook_path, specs_path):
    settings = Settings(
        jwt="",
        environment="dev",
        api_url_override="https://example.test",
        ledger_dir=tmp_path,
        rates_path=tmp_path / "rates.json",
        sheets_path=specs_path,
    )

    with pytest.raises(MissingToken):
        run_sync(workbook_path, settings, log=lambda line: None)

    report = run_sync(
        workbook_path, settings, log=lambda line: None, dry_run=True, rate_override=40.0, today=date(2026, 11, 5)
    )

    assert report.revisions_skipped == 8


def test_environment_picks_api_url_and_its_own_ledger(tmp_path, specs_path):
    settings = Settings(
        jwt="",
        environment="dev",
        api_url_override="",
        ledger_dir=tmp_path,
        rates_path=tmp_path / "rates.json",
        sheets_path=specs_path,
    )

    assert settings.api_url_for("dev") == "https://api-dev.moneycall.io"
    assert settings.api_url_for("prod") == "https://api.moneycall.io"
    assert settings.ledger_path_for("prod") == tmp_path / "ledger.prod.json"
    assert resolve_environment("") == "dev"
    assert resolve_environment("PROD") == "prod"
    with pytest.raises(ValueError):
        resolve_environment("staging")
