from pathlib import Path
from typing import Any

import fitz

from sanad_api.services.docx_io import ParsedSegment
from sanad_api.services.normalization import contains_devanagari, display_normalize

PDF_DOCUMENT_TYPES = {"pdf"}
DEVANAGARI_FONT_PATH = Path("/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc")


def parse_pdf_document(path: Path) -> list[ParsedSegment]:
    document = fitz.open(path)
    try:
        segments: list[ParsedSegment] = []
        sequence = 0
        for page_index, page in enumerate(document):
            page_dict = page.get_text("dict", sort=True)
            for block_index, block in enumerate(page_dict.get("blocks", [])):
                if block.get("type") != 0:
                    continue
                for line_index, line in enumerate(block.get("lines", [])):
                    spans = line.get("spans", [])
                    line_text = display_normalize("".join(span.get("text", "") for span in spans))
                    if not line_text:
                        continue
                    x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
                    if _looks_like_footer_page_number(page, line_text, x0, y0, x1, y1):
                        continue
                    sequence += 1
                    font_size = max((float(span.get("size", 11.0)) for span in spans), default=11.0)
                    segments.append(
                        ParsedSegment(
                            sequence=sequence,
                            segment_type="pdf_line",
                            source_text=line_text,
                            location_json={
                                "kind": "pdf_line",
                                "page_index": page_index,
                                "block_index": block_index,
                                "line_index": line_index,
                                "x0": x0,
                                "y0": y0,
                                "x1": x1,
                                "y1": y1,
                                "font_size": round(font_size, 2),
                            },
                        )
                    )
        return segments
    finally:
        document.close()


def export_pdf_document(
    original_path: Path,
    translations_by_location: list[tuple[dict[str, Any], str]],
    output_path: Path,
) -> Path:
    document = fitz.open(original_path)
    try:
        replacements_by_page: dict[int, list[tuple[dict[str, Any], str]]] = {}
        for location, translated_text in translations_by_location:
            replacements_by_page.setdefault(int(location["page_index"]), []).append((location, translated_text))

        for page_index, replacements in replacements_by_page.items():
            page = document[page_index]
            for location, _ in replacements:
                rect = _rect_from_location(location)
                page.add_redact_annot(rect, fill=(1, 1, 1))
            page.apply_redactions()
            for location, translated_text in replacements:
                _insert_translated_line(page, location, translated_text)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_path, deflate=True, garbage=3)
        return output_path
    finally:
        document.close()


def _rect_from_location(location: dict[str, Any]) -> fitz.Rect:
    return fitz.Rect(
        float(location["x0"]),
        float(location["y0"]),
        float(location["x1"]),
        float(location["y1"]),
    )


def _insert_translated_line(page: fitz.Page, location: dict[str, Any], translated_text: str) -> None:
    rect = _rect_from_location(location)
    base_font_size = max(7.0, min(float(location.get("font_size", 11.0)), 20.0))
    font_name = "helv"
    font_file = None

    if contains_devanagari(translated_text):
        font_name = "sanad-devanagari"
        font_file = str(DEVANAGARI_FONT_PATH)
        page.insert_font(fontname=font_name, fontfile=font_file)

    for font_size in _font_size_steps(base_font_size):
        result = page.insert_textbox(
            rect,
            translated_text,
            fontname=font_name,
            fontfile=font_file,
            fontsize=font_size,
            color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_LEFT,
            lineheight=1.0,
        )
        if result >= 0:
            return

    page.insert_textbox(
        rect,
        translated_text,
        fontname=font_name,
        fontfile=font_file,
        fontsize=6.0,
        color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_LEFT,
        lineheight=1.0,
    )


def _font_size_steps(base_font_size: float) -> list[float]:
    steps = [base_font_size]
    size = base_font_size - 0.5
    while size >= 6.0:
        steps.append(round(size, 2))
        size -= 0.5
    return steps


def _looks_like_footer_page_number(
    page: fitz.Page,
    line_text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> bool:
    text = line_text.strip()
    if not text.isdigit() or len(text) > 3:
        return False

    page_rect = page.rect
    if y0 < page_rect.height * 0.88:
        return False

    center_x = (x0 + x1) / 2
    if not (page_rect.width * 0.35 <= center_x <= page_rect.width * 0.65):
        return False

    return (x1 - x0) <= page_rect.width * 0.08 and (y1 - y0) <= page_rect.height * 0.04
