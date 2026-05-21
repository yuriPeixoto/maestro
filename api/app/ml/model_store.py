"""
Model persistence for Maestro ML — issue #24.

ModelStore manages the lifecycle of trained IsolationForest models:
  - Saves models with a blue/green swap (write to .new.pkl, validate, rename)
  - Stores a JSON metadata sidecar alongside each model
  - Loads all persisted models into memory on startup
  - Provides thread-safe in-memory scoring via get() / score()

Directory layout on disk:
  {models_dir}/
    {server_id}/
      {metric_name}.pkl       ← active model (joblib)
      {metric_name}.json      ← metadata sidecar
      {metric_name}.new.pkl   ← staging (only present during swap)
      {metric_name}.new.json  ← staging (only present during swap)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


@dataclass
class ModelMetadata:
    server_id: str
    metric_name: str
    trained_at: str         # ISO-8601 UTC
    data_range_start: str   # ISO-8601 UTC
    data_range_end: str     # ISO-8601 UTC
    n_samples: int
    contamination: float
    score_min: float        # decision_function min on training set (most anomalous)
    score_max: float        # decision_function max on training set (most normal)
    version: str            # same as trained_at — used to tag anomaly_scores rows


_ModelEntry = tuple[IsolationForest, ModelMetadata]


class ModelStore:
    """In-memory registry of trained IsolationForest models with disk persistence."""

    def __init__(self, models_dir: Path | None = None) -> None:
        self._dir = models_dir or Path(os.getenv("MAESTRO_MODELS_DIR", "/opt/maestro/models"))
        self._models: dict[tuple[str, str], _ModelEntry] = {}

    # ── Startup ───────────────────────────────────────────────────────────────

    def load_all(self) -> int:
        """Scan models_dir and load all valid persisted models into memory.

        Returns the number of models successfully loaded.
        """
        if not self._dir.exists():
            logger.info("model_store: models_dir %s does not exist — no models loaded", self._dir)
            return 0

        count = 0
        for pkl_path in sorted(self._dir.glob("*/*.pkl")):
            if ".new" in pkl_path.name:
                continue  # skip staging artefacts from a previous crashed swap
            meta_path = pkl_path.with_suffix(".json")
            if not meta_path.exists():
                logger.warning("model_store: %s has no metadata sidecar — skipping", pkl_path)
                continue
            try:
                model: IsolationForest = joblib.load(pkl_path)
                meta = ModelMetadata(**json.loads(meta_path.read_text(encoding="utf-8")))
                self._models[(meta.server_id, meta.metric_name)] = (model, meta)
                count += 1
                logger.debug("model_store: loaded %s/%s (n_samples=%d)",
                             meta.server_id, meta.metric_name, meta.n_samples)
            except Exception as exc:
                logger.warning("model_store: failed to load %s: %s", pkl_path, exc)

        logger.info("model_store: loaded %d model(s) from %s", count, self._dir)
        return count

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, server_id: str, metric_name: str) -> _ModelEntry | None:
        return self._models.get((server_id, metric_name))

    def score(self, server_id: str, metric_name: str, features: np.ndarray) -> float | None:
        """Return a normalised anomaly score in [0, 1] for a feature vector.

        Returns None if no model is loaded for this (server_id, metric_name).
        Score semantics: 0.0 = most normal, 1.0 = most anomalous.
        """
        entry = self.get(server_id, metric_name)
        if entry is None:
            return None
        model, meta = entry
        raw = model.decision_function(features.reshape(1, -1))[0]
        score_range = meta.score_max - meta.score_min
        if score_range == 0.0:
            return 0.5
        normalized = (meta.score_max - raw) / score_range
        return float(np.clip(normalized, 0.0, 1.0))

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(
        self,
        server_id: str,
        metric_name: str,
        model: IsolationForest,
        metadata: ModelMetadata,
    ) -> None:
        """Persist model with a blue/green swap and update the in-memory registry.

        Steps:
          1. Serialise to {metric_name}.new.pkl + {metric_name}.new.json
          2. Reload from disk and score a dummy point to validate integrity
          3. Atomically rename .new.pkl → .pkl and .new.json → .json
          4. Update in-memory registry

        Raises RuntimeError if validation fails; staging files are cleaned up.
        """
        model_dir = self._dir / server_id
        model_dir.mkdir(parents=True, exist_ok=True)

        final_pkl = model_dir / f"{metric_name}.pkl"
        final_json = model_dir / f"{metric_name}.json"
        staging_pkl = model_dir / f"{metric_name}.new.pkl"
        staging_json = model_dir / f"{metric_name}.new.json"

        # Write staging
        joblib.dump(model, staging_pkl, compress=3)
        staging_json.write_text(
            json.dumps(asdict(metadata), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Validate: reload from disk and run a dummy inference
        try:
            reloaded: IsolationForest = joblib.load(staging_pkl)
            dummy = np.zeros((1, model.n_features_in_))
            reloaded.decision_function(dummy)
        except Exception as exc:
            staging_pkl.unlink(missing_ok=True)
            staging_json.unlink(missing_ok=True)
            raise RuntimeError(
                f"model_store: validation failed for {server_id}/{metric_name}: {exc}"
            ) from exc

        # Atomic swap
        staging_pkl.replace(final_pkl)
        staging_json.replace(final_json)

        # Update registry
        self._models[(server_id, metric_name)] = (model, metadata)
        logger.info(
            "model_store: saved %s/%s — n_samples=%d trained_at=%s",
            server_id, metric_name, metadata.n_samples, metadata.trained_at,
        )
