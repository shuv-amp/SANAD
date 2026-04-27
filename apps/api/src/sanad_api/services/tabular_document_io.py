import csv
from pathlib import Path

from sanad_api.services.docx_io import ParsedSegment
from sanad_api.services.normalization import display_normalize


TABULAR_DOCUMENT_TYPES = {"csv": ",", "tsv": "\t"}


def parse_tabular_document(path: Path, file_type: str) -> list[ParsedSegment]:
    delimiter = TABULAR_DOCUMENT_TYPES[file_type]
    rows = _read_rows(path, delimiter)
    segments: list[ParsedSegment] = []
    sequence = 0

    for row_index, row in enumerate(rows):
        for cell_index, value in enumerate(row):
            text = display_normalize(value)
            if not text:
                continue
            sequence += 1
            segments.append(
                ParsedSegment(
                    sequence=sequence,
                    segment_type="table_cell",
                    source_text=text,
                    location_json={"kind": "table_cell", "row_index": row_index, "cell_index": cell_index},
                )
            )

    return segments


def export_tabular_document(
    original_path: Path,
    translations_by_location: list[tuple[dict[str, int], str]],
    output_path: Path,
    file_type: str,
) -> Path:
    delimiter = TABULAR_DOCUMENT_TYPES[file_type]
    rows = _read_rows(original_path, delimiter)
    replacements = {(location["row_index"], location["cell_index"]): text for location, text in translations_by_location}

    for row_index, row in enumerate(rows):
        for cell_index, _ in enumerate(row):
            replacement = replacements.get((row_index, cell_index))
            if replacement is not None:
                row[cell_index] = replacement

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerows(rows)
    return output_path


def _read_rows(path: Path, delimiter: str) -> list[list[str]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        return [list(row) for row in reader]

