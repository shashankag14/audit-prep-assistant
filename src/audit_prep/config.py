"""Default settings. Override with CLI flags; there is no .env (no secrets needed)."""

from pathlib import Path

# Repo root / data. Works when running from the repo (editable install).
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# OCR line confidence below this: the value on that line is treated as unreadable.
MIN_OCR_CONFIDENCE = 0.8

# Local LLM: GGUF files run with llama-cpp-python. Downloaded from Hugging Face on
# first use (no account, no key) into the Hugging Face cache. Pick with --model.
MODELS = {
    "qwen2.5-3b": ("Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q4_k_m.gguf"),  # ~2 GB
    "qwen2.5-1.5b": ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),  # ~1 GB
}
DEFAULT_MODEL = "qwen2.5-3b"
LLM_SEED = 42  # with temperature 0: same input, same answer
LLM_CONTEXT = 4096  # tokens; a few retrieved pages + instructions fit
LLM_MAX_TOKENS = 512  # answer length cap
