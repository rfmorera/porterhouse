import json

import pytest

from porterhouse.dtos import RateQuote
from porterhouse.rates import (
    RateService,
    RateUnavailable,
    bcu_rate,
    google_finance_rate,
    parse_bcu_response,
    parse_google_finance_csv,
)

BCU_XML = """<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
<SOAP-ENV:Body><wsbcucotizacionesExecuteResponse xmlns="Cotiza"><Salida>
<respuestastatus><status>1</status><codigoerror>0</codigoerror><mensaje/></respuestastatus>
<datoscotizaciones>
<datoscotizaciones.dato><Fecha>2024-05-22</Fecha><Moneda>2225</Moneda><Nombre>DLS. USA BILLETE</Nombre>
<CodigoISO>USD</CodigoISO><Emisor>INTERBANCARIO</Emisor><TCC>38.10</TCC><TCV>38.50</TCV></datoscotizaciones.dato>
<datoscotizaciones.dato><Fecha>2024-05-23</Fecha><Moneda>2225</Moneda><Nombre>DLS. USA BILLETE</Nombre>
<CodigoISO>USD</CodigoISO><Emisor>INTERBANCARIO</Emisor><TCC>38.20</TCC><TCV>38.60</TCV></datoscotizaciones.dato>
</datoscotizaciones></Salida></wsbcucotizacionesExecuteResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>
"""


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        pass


def test_parses_bcu_quotes_as_mid_rate():
    quotes = parse_bcu_response(BCU_XML)

    assert [(quote.quote_day, quote.rate) for quote in quotes] == [
        ("2024-05-22", 38.3),
        ("2024-05-23", 38.4),
    ]


def test_bcu_uses_the_latest_quote_on_or_before_the_day():
    calls = []

    def post(url, data, headers, timeout):
        calls.append(data.decode())
        return _Response(BCU_XML)

    quote = bcu_rate("2024-05-25", post=post)

    assert quote.quote_day == "2024-05-23"
    assert quote.rate == 38.4
    assert "<cot:FechaDesde>2024-05-15</cot:FechaDesde>" in calls[0]
    assert "<cot:FechaHasta>2024-05-25</cot:FechaHasta>" in calls[0]


def test_rate_service_caches_and_falls_back(tmp_path):
    cache = tmp_path / "rates.json"
    attempts = []

    def failing(day):
        attempts.append(("failing", day))
        raise RuntimeError("offline")

    def working(day):
        attempts.append(("working", day))
        return RateQuote(rate=40.0, source="test", quote_day=day)

    service = RateService(cache, fetchers=[failing, working])

    assert service.uyu_per_usd("2024-05-23").rate == 40.0
    assert service.uyu_per_usd("2024-05-23").rate == 40.0
    assert attempts == [("failing", "2024-05-23"), ("working", "2024-05-23")]
    assert json.loads(cache.read_text())["UYU"]["2024-05-23"]["rate"] == 40.0
    assert RateService(cache, fetchers=[failing]).uyu_per_usd("2024-05-23").source == "test"


def test_rate_service_reports_when_nothing_answers(tmp_path):
    service = RateService(tmp_path / "rates.json", fetchers=[lambda day: None])

    with pytest.raises(RateUnavailable):
        service.uyu_per_usd("2024-05-23")


def test_override_skips_every_source(tmp_path):
    service = RateService(tmp_path / "rates.json", fetchers=[], override=41.5)

    assert service.uyu_per_usd("2024-05-23").rate == 41.5


BCU_ERROR_XML = """<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"><SOAP-ENV:Body>
<wsbcucotizacionesExecuteResponse xmlns="Cotiza"><Salida>
<respuestastatus><status>0</status><codigoerror>2</codigoerror><mensaje>Rango de fechas inválido</mensaje></respuestastatus>
<datoscotizaciones/></Salida></wsbcucotizacionesExecuteResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def test_bcu_error_message_is_surfaced():
    with pytest.raises(RateUnavailable) as caught:
        bcu_rate("2024-05-25", post=lambda *args, **kwargs: _Response(BCU_ERROR_XML))

    assert "codigoerror=2" in str(caught.value)
    assert "Rango de fechas inválido" in str(caught.value)


def test_other_currencies_in_the_bcu_answer_are_ignored():
    xml = BCU_XML.replace(
        "<Fecha>2024-05-23</Fecha><Moneda>2225</Moneda>",
        "<Fecha>2024-05-23</Fecha><Moneda>1111</Moneda>",
    )

    assert [quote.quote_day for quote in parse_bcu_response(xml)] == ["2024-05-22"]


GOOGLE_CSV = """Date,Close
1/3/2022 23:58:00,44.63
1/4/2022 23:58:00,44.55
2022-01-07 23:58:00,"44,41"
"""


def test_google_finance_csv_is_parsed_with_mixed_date_and_number_formats():
    assert parse_google_finance_csv(GOOGLE_CSV) == {
        "2022-01-03": 44.63,
        "2022-01-04": 44.55,
        "2022-01-07": 44.41,
    }


def test_google_finance_uses_latest_day_on_or_before_and_downloads_once():
    calls = []

    def get(url, timeout):
        calls.append(url)
        return _Response(GOOGLE_CSV)

    url = "https://docs.google.com/test/export?format=csv"
    first = google_finance_rate("2022-01-06", get=get, url=url)
    second = google_finance_rate("2022-01-09", get=get, url=url)

    assert (first.quote_day, first.rate, first.source) == ("2022-01-04", 44.55, "google-finance")
    assert second.quote_day == "2022-01-07"
    assert calls == [url]
    with pytest.raises(RateUnavailable):
        google_finance_rate("2022-03-01", get=get, url=url)


def test_google_finance_needs_a_url():
    with pytest.raises(RateUnavailable):
        google_finance_rate("2022-01-06", get=lambda *a, **k: None, url="")
