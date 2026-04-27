import hashlib
import shutil
from pathlib import Path

from fastapi import UploadFile

from sanad_api.config import get_settings


def ensure_storage_root() -> Path:
    root = get_settings().storage_root
    root.mkdir(parents=True, exist_ok=True)
    return root


def document_dir(document_id: str) -> Path:
    path = ensure_storage_root() / "documents" / document_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_upload(document_id: str, upload: UploadFile, extension: str) -> tuple[Path, str]:
    path = document_dir(document_id) / f"original{extension}"
    upload.file.seek(0)
    with path.open("wb") as output:
        shutil.copyfileobj(upload.file, output)
    return path, sha256_file(path)


def export_path(document_id: str, extension: str = ".docx") -> Path:
    return document_dir(document_id) / f"translated{extension}"


def feedback_pack_path(document_id: str) -> Path:
    return document_dir(document_id) / "feedback-pack.zip"
