"""
Small local persistence helpers for the operator cockpit.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4


class JsonListStore:
    """Simple append/remove store backed by a JSON list."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            with open(self.path) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, items: List[Dict[str, Any]]) -> None:
        with open(self.path, "w") as f:
            json.dump(items, f, indent=2)

    def add(self, item: Dict[str, Any]) -> Dict[str, Any]:
        items = self.load()
        entry = {
            "id": item.get("id", str(uuid4())),
            "created_at": item.get("created_at", datetime.now().isoformat()),
            **item,
        }
        items.insert(0, entry)
        self.save(items)
        return entry

    def get(self, item_id: str) -> Dict[str, Any] | None:
        for item in self.load():
            if item.get("id") == item_id:
                return item
        return None

    def remove(self, item_id: str) -> bool:
        items = self.load()
        remaining = [item for item in items if item.get("id") != item_id]
        if len(remaining) == len(items):
            return False
        self.save(remaining)
        return True
