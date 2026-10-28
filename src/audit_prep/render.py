"""Render the brief as one HTML page. Layout only: all wording comes from the items.

- Every value is HTML-escaped. Quotes come from client documents, so they are
  untrusted text and must never become markup.
- Items read by the LLM get an "AI-read" tag (docs/02: mark anything AI generated).
- Document sources link to the cited page; scan sources also show a crop of the
  cited line (the scan is embedded, so the file opens anywhere).
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

from audit_prep import __version__
from audit_prep.models import Item, Source, SourceKind
from audit_prep.rank import Brief, Section

CROP_MARGIN = 8  # px of scan shown around the cited line

_CSS = """
body { font-family: system-ui, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem;
       color: #1f2328; background: #fff; line-height: 1.45; }
header p { margin: .2rem 0; color: #57606a; }
h2 { border-bottom: 1px solid #d0d7de; padding-bottom: .3rem; margin-top: 2rem; }
ul.items { list-style: none; padding: 0; }
li.item { border: 1px solid #d0d7de; border-radius: 6px; padding: .6rem .8rem; margin: .5rem 0; }
.label { display: inline-block; font-size: .8rem; font-weight: 600; padding: .05rem .45rem;
         border-radius: 4px; margin-right: .4rem; }
.Fact { background: #ddf4ff; } .Conflict { background: #ffebe9; }
.Extracted { background: #dafbe1; } .Check-source { background: #fff1e5; }
.Suggestion { background: #fff8c5; } .Missing { background: #eaeef2; }
.ai { font-size: .75rem; color: #8250df; border: 1px solid #8250df; border-radius: 4px;
      padding: 0 .3rem; margin-left: .4rem; }
.why { color: #57606a; font-size: .9rem; margin-top: .2rem; }
ul.sources { margin: .3rem 0 0; padding-left: 1.1rem; font-size: .9rem; }
q { font-style: italic; }
.crop { border: 1px solid #d0d7de; margin-top: .3rem; background-repeat: no-repeat;
        max-width: 100%; }
.empty { color: #57606a; }
footer { margin-top: 2rem; font-size: .8rem; color: #57606a; }
"""


def render_html(brief: Brief, client_dir: Path) -> str:
    """The whole brief as one HTML string. `client_dir` holds the client's docs/ and scans/."""

    audit = brief.audit
    header = (
        f"<h1>Audit prep brief: {escape(brief.client_name)}</h1>"
        f"<p>Certification Body: {escape(brief.scheme)} · Audit type: {escape(str(audit.get('type')))} audit "
        f"<p>Audit ID: {escape(str(audit.get('id')))} · Audit Date: {escape(str(audit.get('date')))}</p>"
        f"<p>Tenant ID: {escape(brief.tenant_id)}</p>"
    )
    sections = "".join(_section(s, client_dir) for s in brief.sections)
    footer = (
        f"<footer>audit-prep {escape(__version__)}.</footer>"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Audit brief {escape(brief.client_id)}</title><style>{_CSS}</style></head>"
        f"<body><header>{header}</header>{sections}{footer}</body></html>"
    )


def _section(section: Section, client_dir: Path) -> str:
    if not section.items:
        body = '<p class="empty">Nothing here.</p>'
    else:
        body = '<ul class="items">' + "".join(_item(i, client_dir) for i in section.items) + "</ul>"
    return f"<section><h2>{escape(section.title)}</h2>{body}</section>"


def _item(item: Item, client_dir: Path) -> str:
    label = escape(item.label.value)
    css = item.label.value.replace(" ", "-")
    read_by_ai = any(s.kind in (SourceKind.DOCUMENT, SourceKind.SCAN) for s in item.sources)
    ai = '<span class="ai">AI-read</span>' if read_by_ai else ""
    sources = "".join(f"<li>{_source(s, client_dir)}</li>" for s in item.sources)
    return (
        f'<li class="item"><span class="label {css}">{label}</span>{escape(item.text)}{ai}'
        f'<div class="why">why: {escape(item.why)}</div>'
        + (f'<ul class="sources">{sources}</ul>' if sources else "")
        + "</li>"
    )


def _source(source: Source, client_dir: Path) -> str:
    """One source line: what it is, a link where there is something to open, and the quote."""

    if source.kind is SourceKind.RECORD:
        return f"record {escape(source.ref)}"

    if source.kind is SourceKind.EXTERNAL:
        name = escape(source.supplied_by or source.ref)
        return f'<a href="{escape(source.ref)}">{name}</a>, checked {source.checked_on}'

    folder = "scans" if source.kind is SourceKind.SCAN else "docs"
    path = _page_file(client_dir / folder / source.ref, source.page)
    where = f"{escape(source.ref)} p.{source.page}"
    link = f'<a href="{escape(path.as_uri())}">{where}</a>' if path else where
    line = f"{link}: <q>{escape(source.quote or '')}</q>"

    if source.kind is SourceKind.SCAN and path and source.box:
        line += _crop(path, source.box)
    return line


def _page_file(folder: Path, page: int | None) -> Path | None:
    """The file for one page (p2.txt, p1.png, ...), or None if it isn't there."""

    if page is None or not folder.is_dir():
        return None
    return next(iter(sorted(folder.glob(f"p{page}.*"))), None)


def _crop(image: Path, box: tuple[int, int, int, int]) -> str:
    """Show only the cited line of the scan: the image as a background, shifted to the box."""

    x, y, w, h = box
    x, y = max(0, x - CROP_MARGIN), max(0, y - CROP_MARGIN)
    w, h = w + 2 * CROP_MARGIN, h + 2 * CROP_MARGIN
    mime = "jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "png"
    data = base64.b64encode(image.read_bytes()).decode("ascii")
    return (
        f'<div class="crop" role="img" aria-label="scan crop" style="width:{w}px;height:{h}px;'
        f"background-image:url(data:image/{mime};base64,{data});"
        f'background-position:-{x}px -{y}px"></div>'
    )
