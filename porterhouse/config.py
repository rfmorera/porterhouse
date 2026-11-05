import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENVIRONMENTS = {
    "dev": "https://api-dev.moneycall.io",
    "prod": "https://api.moneycall.io",
}
DEFAULT_ENVIRONMENT = "dev"
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    jwt: str
    environment: str
    api_url_override: str
    ledger_dir: Path
    rates_path: Path
    sheets_path: Path

    @property
    def has_token(self) -> bool:
        return bool(self.jwt)

    def api_url_for(self, environment: str) -> str:
        if self.api_url_override:
            return self.api_url_override
        return ENVIRONMENTS[environment]

    def ledger_path_for(self, environment: str) -> Path:
        return self.ledger_dir / f"ledger.{environment}.json"


def resolve_environment(value: str) -> str:
    environment = (value or "").strip().lower() or DEFAULT_ENVIRONMENT
    if environment not in ENVIRONMENTS:
        raise ValueError(
            f"Entorno desconocido '{value}', usá uno de: {', '.join(ENVIRONMENTS)}"
        )
    return environment


def load_settings(env_file: str = ".env") -> Settings:
    load_dotenv(ROOT / env_file, override=False)
    return Settings(
        jwt=os.environ.get("MONDAYCALL_JWT", "").strip(),
        environment=resolve_environment(os.environ.get("MONDAYCALL_ENV", "")),
        api_url_override=os.environ.get("MONDAYCALL_API_URL", "").strip().rstrip("/"),
        ledger_dir=_path("PORTERHOUSE_LEDGER_DIR", "data"),
        rates_path=_path("PORTERHOUSE_RATES", "data/rates.json"),
        sheets_path=_path("PORTERHOUSE_SHEETS", "sheets.json"),
    )


def _path(variable: str, default: str) -> Path:
    value = os.environ.get(variable, default).strip() or default
    path = Path(value)
    return path if path.is_absolute() else ROOT / path
