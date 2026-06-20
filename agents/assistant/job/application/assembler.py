"""Assemble the final application PDF.

One PDF = the typeset cover letter (reportlab) followed by the user's original
uploaded documents in plan order. Original PDFs are merged byte-for-byte via
pypdf; non-PDF originals (.txt/.md) are typeset from their file/brain text.

Returns the merged bytes plus a manifest describing what actually made it in, so
the UI and stored record reflect reality even when a file is missing or corrupt.
"""

import io
import logging
import os
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter

from assistant.job.application.models import AvailableDoc, SelectedDoc

logger = logging.getLogger(__name__)

# Original text-file types we typeset (PDFs are merged as-is; everything else is
# skipped because we can't reliably render it).
_TYPESETTABLE_EXTS = {"txt", "md", "markdown", "text", "rst", "log"}


def _paragraph_style():
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=11,
        leading=16,
        spaceAfter=10,
    )


def _typeset_pdf(title: str, body: str) -> bytes:
    """Render plain text into a clean A4 PDF (used for the cover letter and for
    non-PDF original documents)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.4 * cm,
        rightMargin=2.4 * cm,
        topMargin=2.4 * cm,
        bottomMargin=2.4 * cm,
        title=title or "Application",
        author="Private Internet",
    )
    body_style = _paragraph_style()
    title_style = ParagraphStyle(
        "DocTitle", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceAfter=14
    )

    story = []
    if title:
        story.append(Paragraph(escape(title), title_style))
    for block in (body or "").split("\n\n"):
        block = block.strip()
        if not block:
            story.append(Spacer(1, 8))
            continue
        # Preserve single newlines within a paragraph as line breaks.
        html = escape(block).replace("\n", "<br/>")
        story.append(Paragraph(html, body_style))

    doc.build(story)
    return buf.getvalue()


def _append_pdf_bytes(writer: PdfWriter, data: bytes) -> int:
    """Append all pages of a PDF byte-string to the writer. Returns page count."""
    reader = PdfReader(io.BytesIO(data))
    for page in reader.pages:
        writer.add_page(page)
    return len(reader.pages)


def assemble_pdf(
    cover_letter: str,
    selected: list[SelectedDoc],
    docs_by_name: dict[str, AvailableDoc],
) -> tuple[bytes, list[dict]]:
    """Build the merged application PDF. Returns (pdf_bytes, manifest_documents)."""
    writer = PdfWriter()
    manifest: list[dict] = []

    if cover_letter and cover_letter.strip():
        try:
            pages = _append_pdf_bytes(writer, _typeset_pdf("", cover_letter))
            manifest.append(
                {"filename": "cover_letter.pdf", "kind": "cover_letter",
                 "source": "generated", "pages": pages}
            )
        except Exception:
            logger.exception("Failed to typeset cover letter")

    for sel in selected:
        doc = docs_by_name.get(sel.filename)
        if doc is None:
            manifest.append({"filename": sel.filename, "kind": sel.kind,
                             "source": "missing", "skipped": True})
            continue
        try:
            has_disk = bool(doc.disk_path) and os.path.exists(doc.disk_path)
            if doc.ext == "pdf" and has_disk:
                with open(doc.disk_path, "rb") as f:
                    pages = _append_pdf_bytes(writer, f.read())
                manifest.append({"filename": sel.filename, "kind": sel.kind,
                                 "source": "original", "pages": pages})
            elif doc.ext in _TYPESETTABLE_EXTS and has_disk:
                with open(doc.disk_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                pages = _append_pdf_bytes(writer, _typeset_pdf(sel.filename, text))
                manifest.append({"filename": sel.filename, "kind": sel.kind,
                                 "source": "typeset", "pages": pages})
            elif doc.text_excerpt.strip():
                # No usable original on disk — fall back to the brain text excerpt.
                pages = _append_pdf_bytes(writer, _typeset_pdf(sel.filename, doc.text_excerpt))
                manifest.append({"filename": sel.filename, "kind": sel.kind,
                                 "source": "typeset-excerpt", "pages": pages})
            else:
                manifest.append({"filename": sel.filename, "kind": sel.kind,
                                 "source": "unavailable", "skipped": True})
        except Exception:
            logger.exception("Failed to append document %s", sel.filename)
            manifest.append({"filename": sel.filename, "kind": sel.kind,
                             "source": "error", "skipped": True})

    # Never emit a zero-page PDF — pypdf would write an invalid file.
    if len(writer.pages) == 0:
        _append_pdf_bytes(
            writer,
            _typeset_pdf(
                "Application",
                "No documents were available to assemble this application. Add your "
                "CV and certificates to your Brain, then regenerate.",
            ),
        )

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), manifest
