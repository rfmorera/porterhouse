import json
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

import requests

from porterhouse.dtos import RateQuote

BCU_URL = "https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones"
BCU_USD_BILLETE = 2225
BCU_GRUPO = int(os.environ.get("BCU_GRUPO", "0"))
BCU_LOOKBACK_DAYS = 10
CURRENCY_API_URL = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{day}/v1/currencies/usd.json"
)
CURRENCY_API_LOOKBACK_DAYS = 4
CURRENCY_API_FIRST_DAY = "2024-03-02"
TIMEOUT = 20


class RateUnavailable(Exception):
    pass


class RateService:

    def __init__(
        self,
        cache_path: Path,
        fetchers: Optional[list] = None,
        override: Optional[float] = None,
    ):
        self.cache_path = Path(cache_path)
        self.fetchers = fetchers if fetchers is not None else [bcu_rate, currency_api_rate]
        self.override = override
        self.cache = _load_cache(self.cache_path)
        self.fetched = 0

    def uyu_per_usd(self, day: str) -> RateQuote:
        if self.override:
            return RateQuote(rate=self.override, source="override", quote_day=day)
        cached = self.cache["UYU"].get(day)
        if cached:
            return RateQuote.from_dict(cached)
        errors = []
        for fetcher in self.fetchers:
            try:
                quote = fetcher(day)
            except Exception as error:
                errors.append(f"{fetcher.__name__}: {error}")
                continue
            if quote is None:
                errors.append(f"{fetcher.__name__}: sin cotización")
                continue
            self.cache["UYU"][day] = quote.to_dict()
            self.fetched += 1
            self.save()
            return quote
        raise RateUnavailable("; ".join(errors) or "sin fuentes de cotización")

    def save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.cache_path, self.cache)


def bcu_rate(day: str, post: Callable = requests.post) -> Optional[RateQuote]:
    response = bcu_request(day, post)
    response.raise_for_status()
    quotes = parse_bcu_response(response.text)
    usable = [quote for quote in quotes if quote.quote_day <= day]
    if not usable:
        raise RateUnavailable(bcu_failure(response.text))
    best = max(usable, key=lambda quote: quote.quote_day)
    return RateQuote(rate=best.rate, source="bcu", quote_day=best.quote_day)


def bcu_request(day: str, post: Callable = requests.post):
    target = date.fromisoformat(day)
    since = target - timedelta(days=BCU_LOOKBACK_DAYS)
    return post(
        BCU_URL,
        data=bcu_envelope(since.isoformat(), target.isoformat()).encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"Cotizaaction/AWSBCUCOTIZACIONES.Execute"',
        },
        timeout=TIMEOUT,
    )


def bcu_failure(xml: str) -> str:
    status = _tag(xml, "status")
    code = _tag(xml, "codigoerror")
    message = _tag(xml, "mensaje")
    if message or code:
        return f"BCU status={status or '?'} codigoerror={code or '?'} mensaje={message or '(vacío)'}"
    snippet = re.sub(r"\s+", " ", xml)[:200]
    return f"BCU sin datos para la moneda {BCU_USD_BILLETE}; respuesta: {snippet}"


def parse_bcu_response(xml: str) -> list:
    quotes = []
    for block in re.findall(r"<(?:\w+:)?datoscotizaciones\.dato>(.*?)</(?:\w+:)?datoscotizaciones\.dato>", xml, re.S):
        when = _tag(block, "Fecha")
        buy = _tag(block, "TCC")
        sell = _tag(block, "TCV")
        currency = _tag(block, "Moneda")
        if currency and currency.strip() != str(BCU_USD_BILLETE):
            continue
        if not when or not buy or not sell:
            continue
        rate = (float(buy) + float(sell)) / 2
        if rate <= 0:
            continue
        quotes.append(RateQuote(rate=round(rate, 4), source="bcu", quote_day=when[:10]))
    return quotes


def currency_api_rate(day: str, get: Callable = requests.get) -> Optional[RateQuote]:
    target = date.fromisoformat(day)
    for back in range(CURRENCY_API_LOOKBACK_DAYS + 1):
        candidate = (target - timedelta(days=back)).isoformat()
        if candidate < CURRENCY_API_FIRST_DAY:
            raise RateUnavailable(f"currency-api solo tiene datos desde {CURRENCY_API_FIRST_DAY}")
        response = get(CURRENCY_API_URL.format(day=candidate), timeout=TIMEOUT)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        rate = response.json().get("usd", {}).get("uyu")
        if rate:
            return RateQuote(rate=round(float(rate), 4), source="currency-api", quote_day=candidate)
    return None


def bcu_envelope(since: str, until: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cot="Cotiza">'
        "<soapenv:Header/><soapenv:Body><cot:wsbcucotizaciones.Execute><cot:Entrada>"
        f"<cot:Moneda><cot:item>{BCU_USD_BILLETE}</cot:item></cot:Moneda>"
        f"<cot:FechaDesde>{since}</cot:FechaDesde><cot:FechaHasta>{until}</cot:FechaHasta>"
        f"<cot:Grupo>{BCU_GRUPO}</cot:Grupo>"
        "</cot:Entrada></cot:wsbcucotizaciones.Execute></soapenv:Body></soapenv:Envelope>"
    )


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<(?:\w+:)?{name}>(.*?)</(?:\w+:)?{name}>", block, re.S)
    return match.group(1).strip() if match else ""


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {"UYU": {}}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    data.setdefault("UYU", {})
    return data


def _atomic_write(path: Path, data: dict):
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as output:
        json.dump(data, output, indent=2, ensure_ascii=False, sort_keys=True)
        output.write("\n")
    os.replace(temporary, path)
