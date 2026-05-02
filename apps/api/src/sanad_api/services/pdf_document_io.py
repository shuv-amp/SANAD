from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

from sanad_api.services.docx_io import ParsedSegment
from sanad_api.services.normalization import contains_devanagari, display_normalize

PDF_DOCUMENT_TYPES = {"pdf"}
DEVANAGARI_FONT_PATH = Path("/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc")
LARGE_PDF_LINE_THRESHOLD = 180
LARGE_PDF_REGION_MAX_CHARS = 2800
LARGE_PDF_REGION_MAX_LINES = 24
LARGE_PDF_REGION_VERTICAL_GAP = 50.0


@dataclass(frozen=True)
class _PdfLine:
    page_index: int
    block_index: int
    line_index: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float


def parse_pdf_document(path: Path) -> list[ParsedSegment]:
    document = fitz.open(path)
    try:
        lines = _collect_pdf_lines(document)
        if len(lines) <= LARGE_PDF_LINE_THRESHOLD:
            return _line_segments(lines)
        return _region_segments(lines)
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

    if contains_devanagari(translated_text) and DEVANAGARI_FONT_PATH.exists():
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


def _collect_pdf_lines(document: fitz.Document) -> list[_PdfLine]:
    lines: list[_PdfLine] = []
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
                font_size = max((float(span.get("size", 11.0)) for span in spans), default=11.0)
                lines.append(
                    _PdfLine(
                        page_index=page_index,
                        block_index=block_index,
                        line_index=line_index,
                        text=line_text,
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        font_size=round(font_size, 2),
                    )
                )
    return lines


def _line_segments(lines: list[_PdfLine]) -> list[ParsedSegment]:
    return [_line_segment(sequence, line) for sequence, line in enumerate(lines, start=1)]


def _region_segments(lines: list[_PdfLine]) -> list[ParsedSegment]:
    segments: list[ParsedSegment] = []
    current: list[_PdfLine] = []

    def flush_region() -> None:
        nonlocal current
        if not current:
            return
        sequence = len(segments) + 1
        if len(current) == 1:
            segments.append(_line_segment(sequence, current[0]))
        else:
            segments.append(_region_segment(sequence, current))
        current = []

    for line in lines:
        if _looks_structural(line.text):
            flush_region()
            segments.append(_line_segment(len(segments) + 1, line))
            continue
        if current and _starts_new_region(current, line):
            flush_region()
        current.append(line)

    flush_region()
    return segments


def _line_segment(sequence: int, line: _PdfLine) -> ParsedSegment:
    return ParsedSegment(
        sequence=sequence,
        segment_type="pdf_line",
        source_text=line.text,
        location_json={
            "kind": "pdf_line",
            "page_index": line.page_index,
            "block_index": line.block_index,
            "line_index": line.line_index,
            "x0": line.x0,
            "y0": line.y0,
            "x1": line.x1,
            "y1": line.y1,
            "font_size": line.font_size,
        },
    )


def _region_segment(sequence: int, lines: list[_PdfLine]) -> ParsedSegment:
    x0 = min(line.x0 for line in lines)
    y0 = min(line.y0 for line in lines)
    x1 = max(line.x1 for line in lines)
    y1 = max(line.y1 for line in lines)
    font_size = sum(line.font_size for line in lines) / len(lines)
    return ParsedSegment(
        sequence=sequence,
        segment_type="pdf_text_region",
        source_text=_join_region_text(lines),
        location_json={
            "kind": "pdf_text_region",
            "page_index": lines[0].page_index,
            "block_index": lines[0].block_index,
            "line_index": lines[0].line_index,
            "line_count": len(lines),
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "font_size": round(font_size, 2),
        },
    )


def _starts_new_region(current: list[_PdfLine], line: _PdfLine) -> bool:
    previous = current[-1]
    if previous.page_index != line.page_index:
        return True
    if len(current) >= LARGE_PDF_REGION_MAX_LINES:
        return True
    current_chars = sum(len(item.text) for item in current)
    if current_chars + len(line.text) > LARGE_PDF_REGION_MAX_CHARS:
        return True
    vertical_gap = line.y0 - previous.y1
    if vertical_gap > LARGE_PDF_REGION_VERTICAL_GAP:
        return True
    if abs(line.x0 - previous.x0) > 90 and vertical_gap > previous.font_size * 0.7:
        return True
    return False


def _join_region_text(lines: list[_PdfLine]) -> str:
    parts: list[str] = []
    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        if parts and parts[-1].endswith("-") and text[:1].islower():
            parts[-1] = parts[-1][:-1] + text
        else:
            parts.append(text)
    return " ".join(parts)


def _looks_structural(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("#") and stripped[1:].isdigit():
        return True
    if stripped.isdigit():
        return True
    if all(char in ". ·•-–—" for char in stripped) and any(char in stripped for char in ".·•"):
        return True
    return False


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
