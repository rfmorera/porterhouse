import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from porterhouse.dtos import LedgerItem, LedgerRevision


class Ledger:

    def __init__(self, path: Path):
        self.path = Path(path)
        self.items = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            self.items = {
                key: LedgerItem.from_dict(key, value)
                for key, value in data.get("items", {}).items()
            }

    def get(self, key: str) -> Optional[LedgerItem]:
        return self.items.get(key)

    def register_item(
        self, key: str, item_id: str, name: str, account_type: str, subtype: str
    ) -> LedgerItem:
        item = LedgerItem(
            key=key,
            item_id=item_id,
            name=name,
            account_type=account_type,
            subtype=subtype,
        )
        self.items[key] = item
        self.save()
        return item

    def record_revision(
        self,
        key: str,
        day: str,
        amount: float,
        original_amount: float,
        currency: str,
        rate: Optional[float],
    ):
        item = self.items[key]
        item.revisions[day] = LedgerRevision(
            amount=amount,
            original_amount=original_amount,
            currency=currency,
            rate=rate,
            sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "items": {key: item.to_dict() for key, item in sorted(self.items.items())},
        }
        handle, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=self.path.name, suffix=".tmp"
        )
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(temporary, self.path)
