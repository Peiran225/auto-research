"""Literature data types: search hits and retrieved documents with real locators."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from ..models import TextStatus


@dataclass
class PaperMeta:
    canonical_id: str
    title: str
    authors: list[str]
    year: Optional[int]
    url: Optional[str]
    provider: str
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    arxiv_version: Optional[str] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None


@dataclass
class Document:
    """Retrieved text split into addressable units. ``units`` maps a locator ("p.3", "§2",
    "abstract") to its text. Locators cited by evidence must be keys of ``units``."""
    canonical_id: str
    version: str
    units: dict[str, str]
    status: TextStatus
    sha256: str
    path: Optional[str] = None
    note: Optional[str] = None
    read_scope: list[str] = field(default_factory=list)

    def has_locator(self, locator: str) -> bool:
        return locator in self.units

    def excerpt(self, locator: str, needle: str | None = None, width: int = 300) -> Optional[str]:
        text = self.units.get(locator)
        if text is None:
            return None
        if needle:
            i = text.lower().find(needle.lower())
            if i >= 0:
                return text[max(0, i - 60): i + width]
        return text[:width]


class LiteratureProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int) -> list[PaperMeta]: ...

    def fetch_document(self, meta: PaperMeta, dest_dir: Path) -> Document: ...


def normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def canonical_for(meta_doi: str | None, arxiv_id: str | None, fallback: str) -> str:
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if meta_doi:
        return f"doi:{meta_doi.lower()}"
    return fallback


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pdf_units(data: bytes) -> tuple[dict[str, str], TextStatus, str | None]:
    """Split a PDF into page units "p.1", "p.2", ... using pypdf. Pages without text are
    reported so the status can be partial_text instead of full_text."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        return {}, TextStatus.unavailable, f"pdf parse failed: {type(exc).__name__}"
    units: dict[str, str] = {}
    empty = 0
    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            units[f"p.{i}"] = text
        else:
            empty += 1
    if not units:
        return {}, TextStatus.unavailable, "no extractable text (scanned PDF?)"
    status = TextStatus.full_text if empty == 0 else TextStatus.partial_text
    note = f"{empty} page(s) without extractable text" if empty else None
    return units, status, note


def text_units(text: str) -> dict[str, str]:
    """Split plain text / markdown into section units by headings ("§1", "§2", ...)."""
    parts = re.split(r"(?m)^(#{1,3} .*)$", text)
    units: dict[str, str] = {}
    if parts[0].strip():
        units["§0"] = parts[0]
    n = 0
    for i in range(1, len(parts), 2):
        n += 1
        units[f"§{n}"] = parts[i] + "\n" + (parts[i + 1] if i + 1 < len(parts) else "")
    return units or {"§0": text}
