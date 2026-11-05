from datetime import date, datetime

from porterhouse.workbook_reader import WorkbookReader, parse_day


def test_reads_valid_rows_and_warns_about_the_rest(workbook_path, today):
    records, warnings = WorkbookReader(workbook_path, today).read("Efectivo")

    assert [(record.day, record.amount) for record in records] == [
        ("2022-08-29", 1700.0),
        ("2023-01-07", 1882.0),
        ("2023-02-01", -20.0),
    ]
    assert len(warnings) == 3
    assert "sin fecha" in warnings[0]
    assert "31/08/204" in warnings[1]
    assert "fecha futura" in warnings[2]


def test_cumulative_sheet_keeps_every_row(workbook_path, today):
    records, warnings = WorkbookReader(workbook_path, today).read("Inversiones")

    assert [record.nombre for record in records] == ["Gletir", "Gletir", "Binance", "Gletir"]
    assert warnings == []


def test_day_parsing_prefers_day_month_order(today):
    assert parse_day("15/02/2023", today) == ("2023-02-15", None)
    assert parse_day("02/14/2023", today) == ("2023-02-14", None)
    assert parse_day("27/08/26", today) == ("2026-08-27", None)
    assert parse_day(datetime(1900, 1, 30), today)[1].startswith("fecha fuera de rango")
    assert parse_day(date(2026, 11, 6), today)[1].startswith("fecha futura")
    assert parse_day("", today) == (None, "sin fecha")
