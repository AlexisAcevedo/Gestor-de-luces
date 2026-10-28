"""Generate `app.ico` (multi-size) and `app.png` from the shared bulb renderer.

Usage (from the repository root):
    python assets/icon/make_icon.py
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from gestor_luces.adapters.tray.bulb_icon import DEFAULT_GLOW_RGB, render_bulb_image  # noqa: E402

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
OUTPUT_DIR = Path(__file__).resolve().parent


def main() -> int:
    master = render_bulb_image(DEFAULT_GLOW_RGB, 256)
    ico_path = OUTPUT_DIR / "app.ico"
    png_path = OUTPUT_DIR / "app.png"
    # Render each size natively (not downscaled from the master) for crisper small icons.
    frames = [render_bulb_image(DEFAULT_GLOW_RGB, size) for size in ICON_SIZES]
    master.save(ico_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES], append_images=frames)
    master.save(png_path, format="PNG")
    print(f"Wrote {ico_path} and {png_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
