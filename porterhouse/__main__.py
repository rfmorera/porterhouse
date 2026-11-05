import argparse
import sys
from pathlib import Path

from porterhouse.config import load_settings
from porterhouse.runner import MissingToken, run_sync


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="porterhouse")
    commands = parser.add_subparsers(dest="command", required=True)

    sync = commands.add_parser("sync", help="Lee el Excel y envía los cambios a la API")
    sync.add_argument("workbook", type=Path)
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--token", default="")
    sync.add_argument("--rate", type=float, default=None, help="Fuerza una cotización UYU por USD")

    serve = commands.add_parser("serve", help="Levanta la interfaz web")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)
    settings = load_settings()
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
        )
    except MissingToken as error:
        print(f"[error] {error}", file=sys.stderr)
        return 2
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
