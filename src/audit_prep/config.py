"""Default settings. Override with CLI flags; there is no .env (no secrets needed)."""

from pathlib import Path

# Repo root / data. Works when running from the repo (editable install).
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# OCR line confidence below this: the value on that line is treated as unreadable.
MIN_OCR_CONFIDENCE = 0.8
