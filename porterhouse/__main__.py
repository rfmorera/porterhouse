import argparse
import sys
from pathlib import Path

from porterhouse.config import ENVIRONMENTS, load_settings
from porterhouse.runner import MissingToken, run_sync


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="porterhouse")
    commands = parser.add_subparsers(dest="command", required=True)

    sync = commands.add_parser("sync", help="Lee el Excel y envía los cambios a la API")
    sync.add_argument("workbook", type=Path)
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--token", default="")
    sync.add_argument("--env", choices=sorted(ENVIRONMENTS), default=None, help="dev o prod (default: MONDAYCALL_ENV o dev)")
    sync.add_argument("--rate", type=float, default=None, help="Fuerza una cotización UYU por USD")

    rate = commands.add_parser("rate", help="Diagnostica la cotización UYU/USD de una fecha")
    rate.add_argument("day", help="Fecha aaaa-mm-dd")
    rate.add_argument("--raw", action="store_true", help="Imprime el pedido y la respuesta cruda del BCU")

    serve = commands.add_parser("serve", help="Levanta la interfaz web")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)
    settings = load_settings()
    if args.command == "rate":
        return diagnose_rate(args.day, args.raw)
    if args.command == "serve":
        import uvicorn

        uvicorn.run("porterhouse.web:app", host=args.host, port=args.port, reload=False)
        return 0
    try:
        report = run_sync(
            args.workbook,
            settings,
            log=lambda line: print(line, flush=True),
            token=args.token,
            dry_run=args.dry_run,
            rate_override=args.rate,
            environment=args.env or "",
        )
    except MissingToken as error:
        print(f"[error] {error}", file=sys.stderr)
        return 2
    return 1 if report.errors else 0


def diagnose_rate(day: str, raw: bool) -> int:
    from datetime import date, timedelta

    from porterhouse.rates import (
        BCU_LOOKBACK_DAYS,
        BCU_URL,
        RateUnavailable,
        bcu_envelope,
        bcu_rate,
        bcu_request,
        currency_api_rate,
        google_finance_rate,
    )

    if raw:
        since = (date.fromisoformat(day) - timedelta(days=BCU_LOOKBACK_DAYS)).isoformat()
        print(f"POST {BCU_URL}")
        print(bcu_envelope(since, day))
        try:
            response = bcu_request(day)
        except Exception as error:
            print(f"[error] {type(error).__name__}: {error}")
            return 1
        print(f"HTTP {response.status_code}")
        print(response.text)
        return 0
    status = 0
    for name, fetcher in (
        ("google-finance", google_finance_rate),
        ("bcu", bcu_rate),
        ("currency-api", currency_api_rate),
    ):
        try:
            quote = fetcher(day)
        except RateUnavailable as error:
            print(f"{name}: sin cotización ({error})")
            status = 1
        except Exception as error:
            print(f"{name}: error {type(error).__name__}: {error}")
            status = 1
        else:
            print(f"{name}: {quote.rate} UYU/USD (cotización del {quote.quote_day})")
    return status


if __name__ == "__main__":
    sys.exit(main())
