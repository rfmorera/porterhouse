import json
from pathlib import Path

from porterhouse.dtos import SheetSpec

VALID_MODES = {"balance", "cumulative"}


def load_sheet_specs(path: Path) -> list:
    return load_sheet_config(path)[0]


def load_sheet_config(path: Path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    specs = [SheetSpec.from_dict(entry) for entry in data.get("sheets", [])]
    ignored = [str(name) for name in data.get("ignore", [])]
    for spec in specs:
        if spec.mode not in VALID_MODES:
            raise ValueError(f"Modo inválido '{spec.mode}' para la hoja '{spec.sheet}'")
        if spec.currency not in {"USD", "UYU"}:
            raise ValueError(
                f"Moneda no soportada '{spec.currency}' para la hoja '{spec.sheet}'"
            )
    return specs, ignored
