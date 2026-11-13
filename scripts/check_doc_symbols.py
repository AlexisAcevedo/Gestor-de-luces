"""Check that identifier-like backticked symbols in docs/*.md exist under src/.

Warning-only guardrail: prints any referenced identifier that is not found in the
source tree and exits non-zero so CI can surface it without failing the build
(the CI step sets ``continue-on-error``).

Dotted references such as ``WebviewBridge.fit_window_height`` are split on ``.``
so each segment is checked independently (the class and method live on separate
lines).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def _read_source_text() -> str:
    chunks: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def main() -> int:
    source = _read_source_text()
    referenced: set[str] = set()
    for doc in sorted((ROOT / "docs").glob("*.md")):
        for token in re.findall(r"`([^`\n]+)`", doc.read_text(encoding="utf-8")):
            if _IDENTIFIER.fullmatch(token):
                referenced.update(part for part in token.split(".") if part)

    missing = sorted(part for part in referenced if part not in source)
    for part in missing:
        print(f"docs reference not found in src/: {part}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
