"""Draw the synthetic certificate scan used by rich-history auditee (useful as a planted issue).

The expiry line is faded, blurred and smudged so OCR misreads it with low
confidence (RapidOCR reads roughly "Vaid unttos Decenber 202" at ~0.69; every
other line reads correctly at 0.94 or more).
Run once; the PNG is committed: uv run python scripts/make_scan.py
"""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = (
    Path(__file__).resolve().parents[1]
    / "data/tenants/cb-a/clients/rich-history/scans/SCAN-CERT-2024/p1.png"
)
PAPER = 245

LINES = [
    ("CERTIFICATE", 44),
    ("Quality Management System - ISO 9001:2015", 26),
    ("Certificate number: QMS-48213", 26),
    ("Issued to: Brightline Components Ltd", 26),
    ("Sites: Main plant, Leeds; Site 2, Bradford", 26),
    ("Issued on: 02 December 2024", 26),
    ("Valid until: 01 December 2027", 26),  # the faded line
    ("Issued by: CB-A Certification", 26),
]
FADED = "Valid until: 01 December 2027"


def faded_strip(text: str) -> Image.Image:
    """The text in light grey, blurred, with dust on top (values tuned by trying RapidOCR)."""
    random.seed(7)
    strip = Image.new("L", (700, 80), color=PAPER)
    ImageDraw.Draw(strip).text((20, 20), text, fill=150, font=ImageFont.load_default(size=26))
    strip = strip.filter(ImageFilter.GaussianBlur(1.7))
    pixels = strip.load()
    for _ in range(2000):
        pixels[random.randrange(700), random.randrange(80)] = random.randint(150, 245)
    return strip


def main() -> None:
    img = Image.new("L", (1000, 640), color=PAPER)
    draw = ImageDraw.Draw(img)

    y = 50
    for text, size in LINES:
        if text == FADED:
            img.paste(faded_strip(text), (60, y - 20))
        else:
            draw.text((80, y), text, fill=20, font=ImageFont.load_default(size=size))
        y += size + 34

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
