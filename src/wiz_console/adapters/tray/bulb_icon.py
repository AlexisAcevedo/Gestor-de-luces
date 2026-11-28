"""Light-bulb icon renderer shared by the tray, the window icon and `make_icon.py`.

Pure Pillow drawing: no binary assets are required to produce the shape, so the tray
can tint it with the beam color while the packaged `.ico` uses the warm default.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

SUPERSAMPLE = 4
OUTLINE_RGBA = (13, 15, 18, 255)
BASE_RGBA = (138, 146, 158, 255)
DEFAULT_GLOW_RGB = (255, 196, 92)


def render_bulb_image(rgb: tuple[int, int, int], size: int) -> Image.Image:
    """Draw a light bulb (glass + screw base) tinted with `rgb` on a transparent canvas.

    Drawn at 4x resolution and downsampled for smooth edges. A dark outline keeps the
    glass visible on light taskbars. The glass center sits at the canvas center column,
    slightly above the middle, so a tint probe at the canvas center always hits the glass.
    """
    large = size * SUPERSAMPLE
    image = Image.new("RGBA", (large, large), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = max(1, large // 20)  # outline thickness

    cx = large / 2
    cy = large * 0.42
    radius = large * 0.30
    neck_top = cy + radius * 0.55
    neck_bottom = large * 0.72
    neck_half_top = radius * 0.80
    neck_half_bottom = large * 0.13
    base_left, base_right = large * 0.36, large * 0.64
    base_top, base_bottom = neck_bottom, large * 0.90

    def glass(grow: float) -> None:
        draw.ellipse(
            (cx - radius - grow, cy - radius - grow, cx + radius + grow, cy + radius + grow),
            fill=OUTLINE_RGBA if grow else (*rgb, 255),
        )
        draw.polygon(
            [
                (cx - neck_half_top - grow, neck_top - grow),
                (cx + neck_half_top + grow, neck_top - grow),
                (cx + neck_half_bottom + grow, neck_bottom + grow),
                (cx - neck_half_bottom - grow, neck_bottom + grow),
            ],
            fill=OUTLINE_RGBA if grow else (*rgb, 255),
        )

    def base(grow: float) -> None:
        draw.rounded_rectangle(
            (base_left - grow, base_top - grow, base_right + grow, base_bottom + grow),
            radius=large * 0.04,
            fill=OUTLINE_RGBA if grow else BASE_RGBA,
        )

    glass(pad)
    base(pad)
    glass(0)
    base(0)

    # Screw-thread grooves on the base.
    groove_w = max(1, large // 40)
    span = base_bottom - base_top
    for step in (0.33, 0.66):
        y = base_top + span * step
        draw.line((base_left, y, base_right, y), fill=OUTLINE_RGBA, width=groove_w)

    return image.resize((size, size), Image.Resampling.LANCZOS)
