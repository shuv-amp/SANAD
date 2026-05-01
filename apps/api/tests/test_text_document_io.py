import shutil
from pathlib import Path

import pytest
from docx import Document

from sanad_api.services.tabular_document_io import export_tabular_document, parse_tabular_document
from sanad_api.services.text_document_io import export_text_docx, parse_text_document


def test_parse_txt_document_into_ordered_blocks(tmp_path: Path) -> None:
    source = tmp_path / "notice.txt"
    source.write_text(
        "Certificate of Residence Request\n\n"
        "Please submit this form to the Ward Office.\n\n"
        "Fee: NPR 500\n",
        encoding="utf-8",
    )

    segments = parse_text_document(source, "txt")

    assert [segment.source_text for segment in segments] == [
        "Certificate of Residence Request",
        "Please submit this form to the Ward Office.",
        "Fee: NPR 500",
    ]
    assert all(segment.location_json["kind"] == "text_block" for segment in segments)


def test_parse_rtf_document_via_textutil(tmp_path: Path) -> None:
    if shutil.which("textutil") is None:
        pytest.skip("textutil is not available on this runner.")
    source = tmp_path / "notice.rtf"
    source.write_text(
        r"{\rtf1\ansi Certificate of Residence Request\par\par Please submit this form to the Ward Office.\par\par Fee: NPR 500\par}",
        encoding="utf-8",
    )

    segments = parse_text_document(source, "rtf")

    assert [segment.source_text for segment in segments] == [
        "Certificate of Residence Request",
        "Please submit this form to the Ward Office.",
        "Fee: NPR 500",
    ]


def test_export_text_document_as_docx(tmp_path: Path) -> None:
    output = tmp_path / "translated.docx"
    export_text_docx(
        [
            "बसोबास प्रमाणपत्र अनुरोध",
            "कृपया यो फारम वडा कार्यालयमा बुझाउनुहोस्।",
            "शुल्क: NPR ५००",
        ],
        output,
    )

    exported = Document(output)
    assert [paragraph.text for paragraph in exported.paragraphs if paragraph.text] == [
        "बसोबास प्रमाणपत्र अनुरोध",
        "कृपया यो फारम वडा कार्यालयमा बुझाउनुहोस्।",
        "शुल्क: NPR ५००",
    ]


def test_parse_csv_document_into_ordered_cells(tmp_path: Path) -> None:
    source = tmp_path / "notice.csv"
    source.write_text(
        "Field,Value\n"
        "Fee,NPR 500\n"
        "Date,2026-04-21\n",
        encoding="utf-8",
    )

    segments = parse_tabular_document(source, "csv")

    assert [segment.source_text for segment in segments] == [
        "Field",
        "Value",
        "Fee",
        "NPR 500",
        "Date",
        "2026-04-21",
    ]
    assert segments[0].location_json == {"kind": "table_cell", "row_index": 0, "cell_index": 0}
    assert segments[-1].location_json == {"kind": "table_cell", "row_index": 2, "cell_index": 1}


def test_export_csv_document_in_same_format(tmp_path: Path) -> None:
    original = tmp_path / "notice.csv"
    original.write_text(
        "Field,Value\n"
        "Fee,NPR 500\n",
        encoding="utf-8",
    )
    output = tmp_path / "translated.csv"

    export_tabular_document(
        original,
        [
            ({"row_index": 0, "cell_index": 0}, "क्षेत्र"),
            ({"row_index": 0, "cell_index": 1}, "मान"),
            ({"row_index": 1, "cell_index": 0}, "शुल्क"),
            ({"row_index": 1, "cell_index": 1}, "NPR ५००"),
        ],
        output,
        "csv",
    )

    assert output.read_text(encoding="utf-8").splitlines() == [
        "क्षेत्र,मान",
        "शुल्क,NPR ५००",
    ]
