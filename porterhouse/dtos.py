from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SheetSpec:
    sheet: str
    mode: str
    name: str
    account_type: str
    subtype: str
    currency: str
    icon: str
    note: str = ""
    overrides: dict = field(default_factory=dict)

    def for_name(self, nombre: str) -> "SheetSpec":
        override = self.overrides.get(nombre, {})
        return SheetSpec(
            sheet=self.sheet,
            mode=self.mode,
            name=self.name.replace("{nombre}", nombre),
            account_type=override.get("type", self.account_type),
            subtype=override.get("subtype", self.subtype),
            currency=override.get("currency", self.currency),
            icon=override.get("icon", self.icon),
            note=self.note.replace("{nombre}", nombre),
        )

    def to_dict(self) -> dict:
        return {
            "sheet": self.sheet,
            "mode": self.mode,
            "name": self.name,
            "type": self.account_type,
            "subtype": self.subtype,
            "currency": self.currency,
            "icon": self.icon,
            "note": self.note,
            "overrides": dict(self.overrides),
        }

    @staticmethod
    def from_dict(data: dict) -> "SheetSpec":
        return SheetSpec(
            sheet=data["sheet"],
            mode=data.get("mode", "balance"),
            name=data["name"],
            account_type=data["type"],
            subtype=data["subtype"],
            currency=data.get("currency", "USD").upper(),
            icon=data.get("icon", ""),
            note=data.get("note", ""),
            overrides=data.get("overrides", {}),
        )


@dataclass
class RowRecord:
    sheet: str
    row: int
    nombre: str
    amount: float
    description: str
    day: str


@dataclass
class Balance:
    day: str
    original_amount: float
    currency: str
    rows: list
    amount_usd: Optional[float] = None
    rate: Optional[float] = None
    rate_source: str = ""

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "original_amount": self.original_amount,
            "currency": self.currency,
            "rows": list(self.rows),
            "amount_usd": self.amount_usd,
            "rate": self.rate,
            "rate_source": self.rate_source,
        }


@dataclass
class ItemBalances:
    key: str
    spec: SheetSpec
    balances: list

    @property
    def name(self) -> str:
        return self.spec.name


@dataclass
class RateQuote:
    rate: float
    source: str
    quote_day: str

    def to_dict(self) -> dict:
        return {"rate": self.rate, "source": self.source, "quote_day": self.quote_day}

    @staticmethod
    def from_dict(data: dict) -> "RateQuote":
        return RateQuote(
            rate=float(data["rate"]),
            source=data.get("source", ""),
            quote_day=data.get("quote_day", ""),
        )


@dataclass
class LedgerRevision:
    amount: float
    original_amount: float
    currency: str
    rate: Optional[float]
    sent_at: str

    def to_dict(self) -> dict:
        return {
            "amount": self.amount,
            "original_amount": self.original_amount,
            "currency": self.currency,
            "rate": self.rate,
            "sent_at": self.sent_at,
        }

    @staticmethod
    def from_dict(data: dict) -> "LedgerRevision":
        return LedgerRevision(
            amount=float(data["amount"]),
            original_amount=float(data.get("original_amount", data["amount"])),
            currency=data.get("currency", "USD"),
            rate=data.get("rate"),
            sent_at=data.get("sent_at", ""),
        )


@dataclass
class LedgerItem:
    key: str
    item_id: str
    name: str
    account_type: str
    subtype: str
    revisions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "type": self.account_type,
            "subtype": self.subtype,
            "revisions": {
                day: revision.to_dict() for day, revision in sorted(self.revisions.items())
            },
        }

    @staticmethod
    def from_dict(key: str, data: dict) -> "LedgerItem":
        return LedgerItem(
            key=key,
            item_id=data.get("item_id", ""),
            name=data.get("name", ""),
            account_type=data.get("type", ""),
            subtype=data.get("subtype", ""),
            revisions={
                day: LedgerRevision.from_dict(revision)
                for day, revision in data.get("revisions", {}).items()
            },
        )


@dataclass
class PendingRevision:
    balance: Balance
    reason: str


@dataclass
class ItemPlan:
    item: ItemBalances
    existing: Optional[LedgerItem]
    pending: list

    @property
    def is_new(self) -> bool:
        return self.existing is None


@dataclass
class SyncPlan:
    items: list
    warnings: list

    @property
    def pending_count(self) -> int:
        return sum(len(plan.pending) for plan in self.items)


@dataclass
class SyncReport:
    items_created: int = 0
    items_reused: int = 0
    revisions_sent: int = 0
    revisions_skipped: int = 0
    warnings: int = 0
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "items_created": self.items_created,
            "items_reused": self.items_reused,
            "revisions_sent": self.revisions_sent,
            "revisions_skipped": self.revisions_skipped,
            "warnings": self.warnings,
            "errors": list(self.errors),
        }
