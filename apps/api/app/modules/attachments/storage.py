"""Blob storage. Local filesystem for development; an S3-compatible backend plugs in behind the same
interface for production."""

import hashlib
import os
from pathlib import Path
from typing import Protocol

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import ValidationFailed, field_error

CHUNK = 1024 * 1024


class Storage(Protocol):
    async def save(self, key: str, upload: UploadFile, max_bytes: int) -> tuple[int, str]: ...
    def path_for(self, key: str) -> Path: ...


class LocalStorage:
    def __init__(self, base_dir: str) -> None:
        self.base = Path(base_dir).resolve()

    def path_for(self, key: str) -> Path:
        path = (self.base / key).resolve()
        if self.base not in path.parents:
            raise ValueError("invalid storage key")
        return path

    async def save(self, key: str, upload: UploadFile, max_bytes: int) -> tuple[int, str]:
        """Stream to disk while hashing; abort if the file exceeds `max_bytes`."""
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        digest, size = hashlib.sha256(), 0
        try:
            with tmp.open("wb") as fh:
                while chunk := await upload.read(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValidationFailed(
                            "File too large",
                            errors=[
                                field_error("file", f"Maximum size is {max_bytes // (1024 * 1024)} MB", "too_large")
                            ],
                        )
                    digest.update(chunk)
                    fh.write(chunk)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        return size, digest.hexdigest()


def get_storage() -> Storage:
    return LocalStorage(get_settings().attachments_dir)
