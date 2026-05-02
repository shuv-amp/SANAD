import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from sanad_api.models import Document, Segment
from sanad_api.services.docx_io import export_docx
from sanad_api.services.pdf_document_io import PDF_DOCUMENT_TYPES, export_pdf_document
from sanad_api.services.storage import export_path
from sanad_api.services.tabular_document_io import TABULAR_DOCUMENT_TYPES, export_tabular_document, export_tabular_docx
from sanad_api.services.text_document_io import TEXT_DOCUMENT_TYPES, export_text_docx

GOTENBERG_URL = os.environ.get("SANAD_GOTENBERG_URL", "http://gotenberg:3000")
GOTENBERG_TIMEOUT = 60.0


def export_document_file(db: Session, document: Document, output_format: str) -> Path:
    segments = db.scalars(select(Segment).where(Segment.document_id == document.id).order_by(Segment.sequence)).all()
    unapproved = [
        segment.sequence
        for segment in segments
        if not segment.translation or segment.status != "approved" or not segment.translation.approved_text
    ]
    if unapproved:
        raise ValueError(f"Cannot export until all segments are approved. Pending sequence(s): {unapproved}")

    translations_by_location = [
        (segment.location_json, segment.translation.approved_text or segment.translation.candidate_text)
        for segment in segments
    ]
    output_path = export_path(document.id, f".{output_format}")
    try:
        if output_format == "pdf" and document.file_type in PDF_DOCUMENT_TYPES:
            # Layout-preserving PDF → PDF (original path, uses PyMuPDF)
            export_pdf_document(Path(document.original_file_uri), translations_by_location, output_path)
        elif output_format == "pdf":
            # Any non-PDF source → PDF via Gotenberg (DOCX → PDF pipeline)
            _export_via_gotenberg(document, translations_by_location, output_path)
        elif output_format in ("csv", "tsv"):
            export_tabular_document(Path(document.original_file_uri), translations_by_location, output_path, document.file_type)
        elif output_format == "txt":
            text_blocks = [text for _, text in translations_by_location]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("\n\n".join(text_blocks), encoding="utf-8")
        elif output_format == "docx":
            if document.file_type == "docx":
                export_docx(Path(document.original_file_uri), translations_by_location, output_path)
            elif document.file_type in TABULAR_DOCUMENT_TYPES:
                export_tabular_docx(Path(document.original_file_uri), translations_by_location, output_path, document.file_type)
            else:
                export_text_docx([text for _, text in translations_by_location], output_path)
        else:
            raise ValueError(f"SANAD cannot export to format {output_format!r}.")

    except Exception as exc:
        document.status = "export_failed"
        db.commit()
        if output_format == "docx" and document.file_type == "docx":
            raise ValueError(
                "DOCX export could not preserve the original layout mapping. "
                "Fallback: reviewed translations are still available in the segment list; retry with a simpler DOCX."
            ) from exc
        if output_format in ("csv", "tsv"):
            raise ValueError(
                f"SANAD could not generate the translated {output_format.upper()} export for this tabular document. "
                "Reviewed translations are still available in the segment list."
            ) from exc
        if output_format == "pdf":
            raise ValueError(
                "SANAD could not generate the translated PDF. "
                "Reviewed translations are still available in the segment list."
            ) from exc
        raise ValueError(
            f"SANAD could not generate the translated {output_format.upper()} export for this document. "
            "Reviewed translations are still available in the segment list."
        ) from exc

    document.export_file_uri = str(output_path)
    document.status = "exported"
    db.commit()
    return output_path


def _export_via_gotenberg(
    document: Document,
    translations_by_location: list[tuple[dict[str, Any], str]],
    output_path: Path,
) -> None:
    """Generate a translated DOCX in memory, then convert it to PDF via Gotenberg."""
    # Step 1: Generate the translated DOCX into a temporary file
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_docx_path = Path(tmp.name)

    try:
        if document.file_type == "docx":
            # Preserve original DOCX layout for the intermediate file
            export_docx(Path(document.original_file_uri), translations_by_location, tmp_docx_path)
        elif document.file_type in TABULAR_DOCUMENT_TYPES:
            # Preserve TSV/CSV table layout in the intermediate DOCX
            export_tabular_docx(Path(document.original_file_uri), translations_by_location, tmp_docx_path, document.file_type)
        else:
            # Generate a clean text DOCX for any other source type
            export_text_docx([text for _, text in translations_by_location], tmp_docx_path)

        # Step 1.5: Strip 'TableGrid' borders from the intermediate DOCX.
        # LibreOffice renders TableGrid with visible black borders even when
        # Word/Preview shows the same table as borderless.
        _strip_table_grid_borders(tmp_docx_path)

        # Step 2: Send the DOCX to Gotenberg for conversion
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_docx_path, "rb") as docx_file:
            response = httpx.post(
                f"{GOTENBERG_URL}/forms/libreoffice/convert",
                files={"files": ("document.docx", docx_file, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                timeout=GOTENBERG_TIMEOUT,
            )
        if response.status_code != 200:
            raise ValueError(
                f"Gotenberg PDF conversion failed (HTTP {response.status_code}): {response.text[:200]}"
            )

        # Step 3: Save the returned PDF bytes
        output_path.write_bytes(response.content)
    finally:
        # Clean up the temporary DOCX
        tmp_docx_path.unlink(missing_ok=True)


def _strip_table_grid_borders(docx_path: Path) -> None:
    """Remove 'TableGrid' style from tables and set all borders to none.

    LibreOffice applies visible black borders to tables using the 'TableGrid'
    style, while Word/Preview renders them as borderless.  Stripping the style
    and explicitly setting borders to ``none`` ensures the PDF output matches
    the DOCX preview.
    """
    from docx import Document as DocxDocument
    from docx.oxml.ns import qn
    from docx.table import Table as DocxTable
    from lxml import etree

    doc = DocxDocument(str(docx_path))
    modified = False
    for block in doc.iter_inner_content():
        if not isinstance(block, DocxTable):
            continue
        tbl_pr = block._tbl.tblPr
        if tbl_pr is None:
            continue
        style_el = tbl_pr.find(qn("w:tblStyle"))
        if style_el is not None and style_el.get(qn("w:val")) == "TableGrid":
            tbl_pr.remove(style_el)
            # Only add explicit borders if none are already defined
            if tbl_pr.find(qn("w:tblBorders")) is None:
                borders = etree.SubElement(tbl_pr, qn("w:tblBorders"))
                for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                    border = etree.SubElement(borders, qn(f"w:{edge}"))
                    border.set(qn("w:val"), "none")
                    border.set(qn("w:sz"), "0")
                    border.set(qn("w:space"), "0")
                    border.set(qn("w:color"), "auto")
                modified = True

    if modified:
        doc.save(str(docx_path))
