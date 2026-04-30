from pathlib import Path

import fitz

from sanad_api.services.pdf_document_io import export_pdf_document, parse_pdf_document


def test_parse_pdf_document_into_ordered_lines(tmp_path: Path) -> None:
    source = tmp_path / "notice.pdf"
    _create_pdf(
        source,
        [
            "Residence Certificate Notice",
            "Date: 2026-05-02",
            "Fee: NPR 500",
        ],
    )

    segments = parse_pdf_document(source)

    assert [segment.source_text for segment in segments] == [
        "Residence Certificate Notice",
        "Date: 2026-05-02",
        "Fee: NPR 500",
    ]
    assert all(segment.location_json["kind"] == "pdf_line" for segment in segments)


def test_parse_pdf_document_skips_centered_footer_page_numbers(tmp_path: Path) -> None:
    source = tmp_path / "notice.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(56, 72, 520, 100),
        "Residence Certificate Notice",
        fontname="helv",
        fontsize=16,
        color=(0, 0, 0),
    )
    page.insert_textbox(
        fitz.Rect(290, 770, 305, 786),
        "11",
        fontname="helv",
        fontsize=12,
        color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_CENTER,
    )
    doc.save(source)
    doc.close()

    segments = parse_pdf_document(source)

    assert [segment.source_text for segment in segments] == ["Residence Certificate Notice"]


def test_export_pdf_document_in_same_format(tmp_path: Path) -> None:
    original = tmp_path / "notice.pdf"
    output = tmp_path / "translated.pdf"
    _create_pdf(
        original,
        [
            "Residence Certificate Notice",
            "Date: 2026-05-02",
            "Fee: NPR 500",
        ],
    )

    segments = parse_pdf_document(original)
    replacements = [
        (segments[0].location_json, "बसोबास प्रमाणपत्र सूचना"),
        (segments[1].location_json, "मिति: २०२६-०५-०२"),
        (segments[2].location_json, "शुल्क: NPR ५००"),
    ]
    export_pdf_document(original, replacements, output)

    exported = fitz.open(output)
    try:
        text = exported[0].get_text()
    finally:
        exported.close()

    assert "बसोबास प्रमाणपत्र सूचना" in text
    assert "मिति: २०२६-०५-०२" in text
    assert "शुल्क: NPR ५००" in text


def _create_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    for index, line in enumerate(lines):
        page.insert_textbox(
            fitz.Rect(56, y, 520, y + 28),
            line,
            fontname="helv",
            fontsize=16 if index == 0 else 12,
            color=(0, 0, 0),
        )
        y += 34 if index == 0 else 26
    doc.save(path)
    doc.close()
