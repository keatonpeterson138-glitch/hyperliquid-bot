"""Model registry — flat-file storage + SQLite index.

Each trained model lives at:
  ``data/models/<family>/<ts>/{model.pkl, features.json, label.json, metrics.json, config.json}``

``app.db.models`` indexes these rows so the UI can list, promote, and
delete without walking the filesystem.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from backend.db.app_db import AppDB

logger = logging.getLogger(__name__)


@dataclass
class ModelRecord:
    id: str
    family: str
    version: str
    path: str
    features: list[str] = field(default_factory=list)
    label: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    promoted_slot_id: str | None = None
    created_at: datetime | None = None


def _row_to_model(row: Any) -> ModelRecord:
    return ModelRecord(
        id=row["id"],
        family=row["family"],
        version=row["version"],
        path=row["path"],
        features=json.loads(row["features_json"] or "[]"),
        label=row["label"] or "",
        metrics=json.loads(row["metrics_json"] or "{}"),
        config=json.loads(row["config_json"] or "{}"),
        promoted_slot_id=row["promoted_slot_id"],
        created_at=row["created_at"],
    )


class ModelRegistry:
    def __init__(self, db: AppDB, root: Path | str = "data/models") -> None:
        self.db = db
        self.root = Path(root)

    # ── Writes ─────────────────────────────────────────────────────

    def save(
        self,
        *,
        family: str,
        model_obj: Any,
        features: list[str],
        label: str,
        metrics: dict[str, float],
        config: dict[str, Any],
    ) -> ModelRecord:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        version = ts
        model_id = f"{family}_{ts}_{uuid.uuid4().hex[:6]}"
        dir_path = self.root / family / ts
        dir_path.mkdir(parents=True, exist_ok=True)
        model_path = dir_path / "model.pkl"
        joblib.dump(model_obj, model_path)
        (dir_path / "features.json").write_text(json.dumps(features, indent=2))
        (dir_path / "label.json").write_text(json.dumps({"label": label}, indent=2))
        (dir_path / "metrics.json").write_text(json.dumps(metrics, indent=2))
        (dir_path / "config.json").write_text(json.dumps(config, indent=2))

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO models(
                    id, family, version, path, features_json, label,
                    metrics_json, config_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id, family, version, str(dir_path),
                    json.dumps(features),
                    label,
                    json.dumps(metrics),
                    json.dumps(config),
                ),
            )
        return self.get(model_id)  # type: ignore[return-value]

    def promote(self, model_id: str, slot_id: str | None) -> ModelRecord | None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE models SET promoted_slot_id = ? WHERE id = ?",
                (slot_id, model_id),
            )
        return self.get(model_id)

    def delete(self, model_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM models WHERE id = ?", (model_id,))

    # ── Reads ──────────────────────────────────────────────────────

    def get(self, model_id: str) -> ModelRecord | None:
        row = self.db.fetchone("SELECT * FROM models WHERE id = ?", (model_id,))
        return _row_to_model(row) if row else None

    def list(self, *, family: str | None = None) -> list[ModelRecord]:
        clauses = []
        params: list[Any] = []
        if family is not None:
            clauses.append("family = ?")
            params.append(family)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.fetchall(
            f"SELECT * FROM models{where} ORDER BY created_at DESC", tuple(params)
        )
        return [_row_to_model(r) for r in rows]

    def load_model(self, record: ModelRecord) -> Any:
        model_file = Path(record.path) / "model.pkl"
        if not model_file.exists():
            raise FileNotFoundError(f"Model file missing: {model_file}")
        return joblib.load(model_file)
