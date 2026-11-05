from datetime import date, datetime
from pathlib import Path

import openpyxl
import pytest

TODAY = date(2026, 11, 5)


def write_workbook(path: Path, sheets: dict) -> Path:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        sheet["B2"] = "Nombre"
        sheet["C2"] = "Monto"
        sheet["D2"] = "Descripcion"
        sheet["E2"] = "Fecha"
        for offset, (nombre, monto, descripcion, fecha) in enumerate(rows, start=3):
            sheet.cell(offset, 2, nombre)
            sheet.cell(offset, 3, monto)
            sheet.cell(offset, 4, descripcion)
            sheet.cell(offset, 5, fecha)
    workbook.save(path)
    return path


@pytest.fixture
def today():
    return TODAY


@pytest.fixture
def workbook_path(tmp_path):
    return write_workbook(
        tmp_path / "book.xlsx",
        {
            "Efectivo": [
                ("Estado", 1700, None, datetime(2022, 8, 29)),
                ("Estado", 1182, None, None),
                ("Estado", 1882, None, "07/01/2023"),
                ("Estado", 1500, None, "31/08/204"),
                ("Estado", 1600, None, datetime(2027, 1, 1)),
                ("Estado", -20, None, datetime(2023, 2, 1)),
            ],
            "Pesos Rafael": [
                ("Estado", 69370.45, None, datetime(2023, 2, 10)),
                ("Estado", 40000, None, datetime(2023, 3, 10)),
            ],
            "Inversiones": [
                ("Gletir", 2000, None, datetime(2025, 3, 7)),
                ("Gletir", 5000, None, datetime(2025, 3, 12)),
                ("Binance", 259, None, datetime(2026, 2, 6)),
                ("Gletir", -7000, None, datetime(2025, 3, 12)),
            ],
        },
    )


@pytest.fixture
def specs_path(tmp_path):
    path = tmp_path / "sheets.json"
    path.write_text(
        """
{
  "sheets": [
    {"sheet": "Efectivo", "mode": "balance", "name": "Efectivo", "type": "depository",
     "subtype": "cash management", "currency": "USD", "icon": "wallet", "note": "Excel: Efectivo"},
    {"sheet": "Pesos Rafael", "mode": "balance", "name": "Pesos Rafael", "type": "depository",
     "subtype": "checking", "currency": "UYU", "icon": "bank"},
    {"sheet": "Inversiones", "mode": "cumulative", "name": "Inversión {nombre}", "type": "investment",
     "subtype": "brokerage", "currency": "USD", "icon": "investment",
     "overrides": {"Binance": {"subtype": "crypto exchange", "icon": "crypto"}}},
    {"sheet": "No existe", "mode": "balance", "name": "Nada", "type": "depository",
     "subtype": "checking", "currency": "USD", "icon": "bank"}
  ]
}
""",
        encoding="utf-8",
    )
    return path
