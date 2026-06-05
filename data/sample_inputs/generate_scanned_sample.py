"""
generate_scanned_sample.py
---------------------------
Render a legal notice to a deliberately low-quality "scanned" PNG so the
pytesseract OCR path in processor.py can be exercised on a real image (not a
.txt passthrough).

We add the kind of degradation a real scan/photo has — grayscale, a slight
rotation, sensor noise, and a faint blur — so OCR has to actually work for it.

Run:
    python data/sample_inputs/generate_scanned_sample.py
Produces:
    data/sample_inputs/04_scanned_notice.png
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    import numpy as np
except ImportError:  # numpy ships with the project deps, but degrade anyway
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "04_scanned_notice.png")

NOTICE_TEXT = """NOTICE OF DEFAULT AND DEMAND TO CURE

Case No. CV-2021-08842
Superior Court of California, County of Santa Clara

TO: Northgate Packaging Solutions, LLC (Defendant)
FROM: Meridian Logistics, Inc. (Plaintiff)
DATE: April 2, 2021

PLEASE TAKE NOTICE that under the Supply Agreement dated
January 15, 2021, you agreed to deliver 50,000 corrugated
shipping containers per month at $2.40 per unit.

In March 2021 you delivered only 32,000 units, a shortfall of
18,000 units below the contractual minimum. This constitutes a
material breach of the Agreement.

DEMAND: You are hereby required to CURE this default within
thirty (30) days of the date of this notice. Failure to cure
will result in Meridian procuring cover at prevailing market
rates and pursuing all damages, including cover damages,
pre-judgment interest, and costs of suit.

Dana Whitfield, Esq.
Whitfield & Associates LLP
Counsel for Plaintiff
"""


def _load_font(size: int):
    """Try a few common system fonts; fall back to PIL's default."""
    for path in (
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def main() -> None:
    W, H = 1000, 1300
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    font = _load_font(24)

    # Lay out the text with simple line spacing.
    y = 60
    for line in NOTICE_TEXT.splitlines():
        draw.text((70, y), line, fill=(15, 15, 15), font=font)
        y += 34

    # --- Degrade it to look scanned ------------------------------------- #
    img = img.convert("L")                       # grayscale
    img = img.rotate(-1.2, expand=False, fillcolor=255)  # slight skew
    img = img.filter(ImageFilter.GaussianBlur(0.6))      # soft focus

    if np is not None:                           # sensor noise
        arr = np.asarray(img).astype("int16")
        noise = np.random.normal(0, 12, arr.shape).astype("int16")
        arr = np.clip(arr + noise, 0, 255).astype("uint8")
        img = Image.fromarray(arr, mode="L")

    img.save(OUT_PATH, "PNG")
    print(f"wrote {OUT_PATH} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
