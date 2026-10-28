"""Document pages, OCR and a keyword index for one client.

- Pages: every submitted document is split into pages. Page triage by file type:
  `.txt` = text page (in production: a PDF page with a text layer),
  `.png` / `.jpg` = image page, read with OCR.
- OCR: RapidOCR (local, pip only, runs on CPU) gives text lines with a confidence and a box.
  Tests use a fake OCR, never the real engine.
- Index: plain keyword search over one client's pages. It is built per audit
  and refuses pages from another tenant, so a search can't leak across tenants.

Layout on disk: <client>/docs/<doc id>/p1.txt, <client>/scans/<doc id>/p1.png
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from audit_prep.config import DATA_DIR, MIN_OCR_CONFIDENCE
from audit_prep.loader import AuditData, SchemeProfile
from audit_prep.models import Item, Label, SourceKind

_SAFE_DOC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


class OcrLine(BaseModel):
    """One line of text read from an image by OCR, with a confidence and a box."""

    model_config = ConfigDict(frozen=True)

    text: str
    confidence: float  # 0..1, from the OCR engine
    box: tuple[int, int, int, int]  # x, y, width, height on the image


class Page(BaseModel):
    """One page of one document, tagged with its tenant."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    doc_id: str
    page: int  # 1-based
    kind: SourceKind  # DOCUMENT (text page) or SCAN (image page)
    text: str
    lines: tuple[OcrLine, ...] = ()  # only for scans


class Ocr(Protocol):
    def read(self, image: Path) -> list[OcrLine]: ...


class RapidOcr:
    """Local OCR with PP-OCR models (RapidOCR). The engine loads on first use."""

    def __init__(self) -> None:
        self._engine = None

    def read(self, image: Path) -> list[OcrLine]:
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()

        result, _ = self._engine(str(image))
        return [
            OcrLine(text=text, confidence=float(conf), box=_to_xywh(corners))
            for corners, text, conf in result or []
        ]


def load_pages(
    data: AuditData, ocr: Ocr, data_dir: Path = DATA_DIR
) -> tuple[tuple[Page, ...], tuple[Item, ...]]:
    """Pages of every submitted document.

    Also returns 'Missing' items for files that can't be used.
    """

    client_dir = data_dir / "tenants" / data.tenant_id / "clients" / data.client_id
    pages: list[Page] = []
    items: list[Item] = []

    for doc in data.records.get("submitted_documents", []):
        doc_id = doc.get("id") or ""
        if not _SAFE_DOC_ID.match(doc_id):
            continue  # empty id is reported by quality.py; anything else is not a path we follow

        # if the document is listed as submitted, but no file was found, report it as Missing.
        files = _page_files(client_dir, doc_id)
        if not files:
            items.append(_missing(f"{doc_id}: listed as submitted, but no file was found"))
            continue

        # read each page of the document. If the page has no readable text, report it as Missing.
        for number, path in enumerate(files, start=1):
            page = _read_page(data.tenant_id, doc_id, number, path, ocr)

            if page.text.strip():
                pages.append(page)
            else:
                items.append(_missing(f"{doc_id} p.{number}: no readable text"))

    return tuple(pages), tuple(items)


def low_confidence_lines(
    page: Page, quote: str, min_confidence: float = MIN_OCR_CONFIDENCE
) -> list[OcrLine]:
    """OCR lines holding `quote` whose confidence is too low to trust. Empty for text pages.

    Matching ignores case and spaces, because OCR often drops spaces
    ("Certificatenumber:QMS-48213").
    """
    return [line for line in lines_holding(page, quote) if line.confidence < min_confidence]


def lines_holding(page: Page, quote: str) -> list[OcrLine]:
    """OCR lines that contain `quote`, ignoring case and spaces. Empty for text pages."""
    target = _for_ocr_match(quote)
    return [line for line in page.lines if target and target in _for_ocr_match(line.text)]


class Hit(BaseModel):
    """One page that matched one or more search terms, with the terms found on it."""

    model_config = ConfigDict(frozen=True)

    page: Page
    matched: tuple[str, ...]  # which terms were found on the page


class KeywordIndex:
    """Keyword search over the pages of one tenant. Score = number of distinct terms found."""

    def __init__(self, tenant_id: str, pages: tuple[Page, ...]) -> None:
        others = {p.tenant_id for p in pages} - {tenant_id}
        if others:
            raise ValueError(f"index for {tenant_id!r} got pages from {sorted(others)}")
        self._pages = [(page, _for_search(page.text)) for page in pages]

    def search(self, terms: list[str], top_k: int = 3) -> list[Hit]:
        """Return the pages that contain one or more of the search terms. 
        Later replaced by a proper index (eg. HNSW + BM25), but this is enough for now."""

        hits = []
        for page, text in self._pages:
            matched = tuple(t for t in terms if re.search(rf"\b{re.escape(t.lower())}\b", text))
            if matched:
                hits.append(Hit(page=page, matched=matched))

        # Fixed order: most terms first, then document and page, so results repeat exactly.
        hits.sort(key=lambda h: (-len(h.matched), h.page.doc_id, h.page.page))
        return hits[:top_k]


def expand_terms(terms: list[str], profile: SchemeProfile) -> list[str]:
    """Add the scheme's synonyms: "supplier evaluation" also finds "vendor evaluation"."""
    out = list(terms)
    for canonical, synonyms in profile.terms.items():
        group = [canonical, *synonyms]
        if any(t.lower() in (g.lower() for g in group) for t in terms):
            out += [g for g in group if g not in out]
    return out


def _page_files(client_dir: Path, doc_id: str) -> list[Path]:
    """All the pages of a document, sorted by page number. Empty if the document is missing."""
    for folder in (client_dir / "docs" / doc_id, client_dir / "scans" / doc_id):
        if folder.is_dir():
            files = [p for p in folder.iterdir() if re.fullmatch(r"p\d+", p.stem)]
            return sorted(files, key=lambda p: int(p.stem[1:]))
    return []


def _read_page(tenant_id: str, doc_id: str, number: int, path: Path, ocr: Ocr) -> Page:
    """Read one page of a document, either text or image.

    Returns a Page with the text and OCR lines.
    """
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        lines = tuple(ocr.read(path))
        text = "\n".join(line.text for line in lines)
        kind = SourceKind.SCAN
    else:
        lines = ()
        text = path.read_text(encoding="utf-8")
        kind = SourceKind.DOCUMENT
    return Page(tenant_id=tenant_id, doc_id=doc_id, page=number, kind=kind, text=text, lines=lines)


def _missing(text: str) -> Item:
    """A Missing item for a document that could not be read, so nothing in it was checked."""

    return Item(
        label=Label.MISSING,
        text=text,
        why="document could not be read, so nothing in it was checked",
        rule="document_unreadable",
    )


def _to_xywh(corners: list[list[float]]) -> tuple[int, int, int, int]:
    """Convert the OCR engine's 4 corners to x, y, width, height."""

    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))


def _for_search(text: str) -> str:
    """Lowercase and COLLAPSE whitespace to one space. Keeps word boundaries for keyword search."""
    return re.sub(r"\s+", " ", text.lower())


def _for_ocr_match(text: str) -> str:
    """Lowercase and REMOVES ALL whitespace. OCR drops spaces, so match quotes without them."""
    return re.sub(r"\s+", "", text.lower())
