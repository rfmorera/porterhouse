import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_API_URL = "https://api-dev.moneycall.io"
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    jwt: str
    api_url: str
    ledger_path: Path
    rates_path: Path
    sheets_path: Path

    @property
    def has_token(self) -> bool:
        return bool(self.jwt)


def load_settings(env_file: str = ".env") -> Settings:
    load_dotenv(ROOT / env_file, override=False)
    return Settings(
        jwt=os.environ.get("MONDAYCALL_JWT", "").strip(),
        api_url=os.environ.get("MONDAYCALL_API_URL", DEFAULT_API_URL).strip().rstrip("/"),
        ledger_path=_path("PORTERHOUSE_LEDGER", "data/ledger.json"),
        rates_path=_path("PORTERHOUSE_RATES", "data/rates.json"),
        sheets_path=_path("PORTERHOUSE_SHEETS", "sheets.json"),
    )


def _path(variable: str, default: str) -> Path:
    value = os.environ.get(variable, default).strip() or default
    path = Path(value)
    return path if path.is_absolute() else ROOT / path
