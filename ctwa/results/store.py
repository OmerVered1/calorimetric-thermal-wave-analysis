"""Blocking reads and writes of the results tables over CloudClient. Never call on the GUI thread.

Errors are the client's own: NotLoggedIn, Offline, ServerError."""
from __future__ import annotations

from typing import Dict, List, Optional

from ctwa.results.columns import LIST_COLUMNS

__all__ = ["ResultsStore", "PAGE", "GRAPH_CHUNK"]

TABLE = "analyses"
PRESETS = "alpha_presets"
PAGE = 1000        # PostgREST returns at most this many rows per request
GRAPH_CHUNK = 20   # plots are big: a few per request


class ResultsStore:
    def __init__(self, client) -> None:
        self.client = client

    def fetch_rows(self) -> List[dict]:
        """Every analysis (LIST_COLUMNS, newest first), page by page until a short page."""
        out: List[dict] = []
        offset = 0
        while True:
            page = self.client.select(TABLE, {
                "select": ",".join(LIST_COLUMNS), "order": "created_at.desc",
                "limit": str(PAGE), "offset": str(offset)})
            out.extend(page)
            if len(page) < PAGE:
                return out
            offset += PAGE

    def fetch_graph_images(self, ids: List[int]) -> Dict[int, Optional[str]]:
        """id -> stored plot (base64), None where the row has none. Every requested id is a key."""
        wanted = list(dict.fromkeys(ids))
        out: Dict[int, Optional[str]] = {i: None for i in wanted}
        for i in range(0, len(wanted), GRAPH_CHUNK):
            part = wanted[i:i + GRAPH_CHUNK]
            for row in self.client.select(TABLE, {
                    "select": "id,graph_image",
                    "id": "in.(" + ",".join(str(x) for x in part) + ")"}):
                if row.get("id") in out:
                    out[row["id"]] = row.get("graph_image") or None
        return out

    def fetch_presets(self) -> List[dict]:
        return self.client.select(PRESETS, {"select": "*", "order": "material_name.asc"})

    def update_fields(self, id: int, changes: dict) -> dict:
        """Send only the changed fields (nothing at all when there are none)."""
        if not changes:
            return {}
        return self.client.update(TABLE, id, dict(changes))

    def delete(self, id: int) -> None:
        self.client.delete(TABLE, id)

    def insert(self, table: str, row: dict) -> dict:
        return self.client.insert(table, dict(row))

    def delete_preset(self, id) -> None:
        self.client.delete(PRESETS, id)

    def insert_preset(self, row: dict) -> dict:
        return self.client.insert(PRESETS, dict(row))
