"""Regenerate ``ui/scenes.json`` from the domain scene catalog (single source of truth).

The built-in scene catalog lives in ``gestor_luces/domain/scenes.py``
(``BUILTIN_SCENES``). This script serializes it to ``ui/scenes.json`` so the web
frontend can paint the scene grid at first paint without waiting for the backend
handshake and without a second hardcoded copy in ``ui/app.js``.

Run it from the repository root whenever the domain catalog changes::

    python scripts/export_scenes.py

The committed ``ui/scenes.json`` is kept in sync by
``tests/test_scene_catalog_sync.py``, which fails when the domain and the JSON
diverge.
"""

from __future__ import annotations

import json
from pathlib import Path

from gestor_luces.domain.scenes import BUILTIN_SCENES

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ui" / "scenes.json"


def build_payload() -> list[dict[str, object]]:
    """Serialize the catalog exactly as the UI consumes it."""
    return [scene.to_dict() for scene in BUILTIN_SCENES]


def main() -> int:
    payload = build_payload()
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT} ({len(payload)} scenes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
