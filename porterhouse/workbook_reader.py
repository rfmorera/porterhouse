import re
from datetime import date, datetime
from pathlib import Path

import openpyxl

from porterhouse.dtos import RowRecord

HEADER_LABELS = {
    "nombre": "nombre",
    "monto": "amount",
    "descripcion": "description",
    "descripción": "description",
    "fecha": "day",
}
STRING_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y")
MIN_YEAR = 2000
BLANK_ROWS_TO_STOP = 200


class SheetNotFound(Exception):
    pass


class WorkbookReader:

    def __init__(self, path: Path, today: date):
        self.path = Path(path)
        self.today = today
        self.workbook = openpyxl.load_workbook(self.path, data_only=True)

    @property
    def sheet_names(self) -> list:
        return list(self.workbook.sheetnames)

    def read(self, sheet: str):
        if sheet not in self.workbook.sheetnames:
            raise SheetNotFound(sheet)
        worksheet = self.workbook[sheet]
        header_row, columns = _find_header(worksheet)
        if header_row is None:
            return [], [f"[{sheet}] no se encontró la fila de encabezado (Nombre/Monto/Fecha)"]
        records = []
        warnings = []
        blank_streak = 0
        row = header_row
        while blank_streak < BLANK_ROWS_TO_STOP and row < worksheet.max_row:
            row += 1
            nombre = _text(worksheet.cell(row, columns["nombre"]).value)
            raw_amount = worksheet.cell(row, columns["amount"]).value
            if not nombre and raw_amount is None:
                blank_streak += 1
                continue
            blank_streak = 0
            if not nombre:
                warnings.append(f"[{sheet}] fila {row}: sin nombre, omitida")
                continue
            amount, amount_warning = _amount(raw_amount)
            if amount_warning:
                warnings.append(f"[{sheet}] fila {row}: {amount_warning}, omitida")
                continue
            day_column = columns.get("day")
            raw_day = worksheet.cell(row, day_column).value if day_column else None
            day, day_warning = parse_day(raw_day, self.today)
            if day_warning:
                warnings.append(f"[{sheet}] fila {row}: {day_warning}, omitida")
                continue
            description_column = columns.get("description")
            description = (
                _text(worksheet.cell(row, description_column).value)
                if description_column
                else ""
            )
            records.append(
                RowRecord(
                    sheet=sheet,
                    row=row,
                    nombre=nombre,
                    amount=amount,
                    description=description,
                    day=day,
                )
            )
        return records, warnings


def parse_day(value, today: date):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "sin fecha"
    parsed = None
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        parsed = _parse_string_day(value.strip())
        if parsed is None:
            return None, f"fecha no reconocida '{value.strip()}'"
    else:
        return None, f"fecha no reconocida '{value}'"
    if parsed.year < MIN_YEAR:
        return None, f"fecha fuera de rango '{parsed.isoformat()}'"
    if parsed > today:
        return None, f"fecha futura '{parsed.isoformat()}'"
    return parsed.isoformat(), None


def _parse_string_day(text: str):
    for pattern in STRING_DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _amount(value):
    if value is None:
        return None, "monto vacío"
    if isinstance(value, bool):
        return None, "monto inválido"
    if isinstance(value, (int, float)):
        return round(float(value), 2), None
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("="):
            return None, "fórmula sin valor calculado (guardá el archivo desde Excel)"
        cleaned = re.sub(r"[^\d,.\-]", "", text)
        if cleaned.count(",") and cleaned.count("."):
            cleaned = cleaned.replace(",", "")
        elif cleaned.count(",") == 1:
            cleaned = cleaned.replace(",", ".")
        try:
            return round(float(cleaned), 2), None
        except ValueError:
            return None, f"monto no numérico '{text}'"
    return None, f"monto no reconocido '{value}'"


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _find_header(worksheet):
    for row in range(1, min(worksheet.max_row, 20) + 1):
        columns = {}
        for column in range(1, min(worksheet.max_column, 15) + 1):
            label = _text(worksheet.cell(row, column).value).lower()
            key = HEADER_LABELS.get(label)
            if key and key not in columns:
                columns[key] = column
        if "nombre" in columns and "amount" in columns:
            return row, columns
    return None, {}
