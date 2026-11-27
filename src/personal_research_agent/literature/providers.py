"""Real metadata providers (arXiv API, OpenAlex), local import, and the fixture provider.

Network calls go through ``httpx`` with bounded retries/back-off. In offline_local mode the
network guard makes any such call fail, and the controller never constructs these providers.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from ..models import TextStatus
from .base import Document, PaperMeta, canonical_for, pdf_units, sha256_bytes, text_units

ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
USER_AGENT = "personal-research-agent/0.1 (research tooling)"


class LiteratureError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code   # RATE_LIMITED | UNAVAILABLE | NETWORK | PARSE


def _get(url: str, timeout: float, retries: int = 2, params: dict | None = None) -> bytes:
    import httpx

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
                resp = client.get(url, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                last = LiteratureError("RATE_LIMITED" if resp.status_code == 429 else "UNAVAILABLE",
                                       f"HTTP {resp.status_code} from {urllib.parse.urlparse(url).netloc}")
                time.sleep(min(3 * (attempt + 1), 15))
                continue
            if resp.status_code in (401, 402, 403, 404):
                raise LiteratureError("UNAVAILABLE", f"HTTP {resp.status_code} for {url}")
            resp.raise_for_status()
            return resp.content
        except LiteratureError:
            raise
        except Exception as exc:
            last = LiteratureError("NETWORK", f"{type(exc).__name__}: {str(exc)[:200]}")
            time.sleep(min(3 * (attempt + 1), 15))
    assert last is not None
    raise last  # type: ignore[misc]


# ------------------------------------------------------------------------------ arXiv
def parse_arxiv_feed(xml_bytes: bytes) -> list[PaperMeta]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise LiteratureError("PARSE", f"arXiv feed: {exc}") from exc
    out: list[PaperMeta] = []
    for e in root.findall("a:entry", ATOM):
        raw_id = (e.findtext("a:id", "", ATOM) or "").strip()
        m = re.search(r"arxiv\.org/abs/([^v\s]+)(v\d+)?$", raw_id)
        title = re.sub(r"\s+", " ", e.findtext("a:title", "", ATOM) or "").strip()
        if not m or not title or title.lower() == "error":
            continue
        arxiv_id, version = m.group(1), (m.group(2) or "")
        doi = e.findtext("arxiv:doi", None, ATOM)
        published = e.findtext("a:published", "", ATOM) or ""
        pdf = next((l.get("href") for l in e.findall("a:link", ATOM) if l.get("title") == "pdf"), None)
        out.append(PaperMeta(
            canonical_id=canonical_for(None, arxiv_id, raw_id), title=title,
            authors=[(a.findtext("a:name", "", ATOM) or "").strip() for a in e.findall("a:author", ATOM)],
            year=int(published[:4]) if published[:4].isdigit() else None,
            url=f"https://arxiv.org/abs/{arxiv_id}{version}", provider="arxiv", doi=doi,
            arxiv_id=arxiv_id, arxiv_version=version or None,
            abstract=re.sub(r"\s+", " ", e.findtext("a:summary", "", ATOM) or "").strip() or None,
            pdf_url=pdf or f"https://arxiv.org/pdf/{arxiv_id}{version}",
        ))
    return out


class ArxivProvider:
    name = "arxiv"
    API = "https://export.arxiv.org/api/query"

    def __init__(self, timeout: float = 30):
        self.timeout = timeout

    def search(self, query: str, max_results: int) -> list[PaperMeta]:
        data = _get(self.API, self.timeout, params={"search_query": f"all:{query}", "start": 0,
                                                      "max_results": max_results})
        return parse_arxiv_feed(data)

    def by_id(self, arxiv_id: str) -> list[PaperMeta]:
        return parse_arxiv_feed(_get(self.API, self.timeout, params={"id_list": arxiv_id}))

    def fetch_document(self, meta: PaperMeta, dest_dir: Path) -> Document:
        version = meta.arxiv_version or "unversioned"
        if not meta.pdf_url:
            return _unavailable(meta, version, "no PDF link")
        try:
            data = _get(meta.pdf_url, self.timeout)
        except LiteratureError as exc:
            return _unavailable(meta, version, str(exc))
        return _document_from_pdf(meta.canonical_id, version, data, dest_dir)


# ------------------------------------------------------------------------------ OpenAlex
def _openalex_abstract(inv: Optional[dict]) -> Optional[str]:
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def parse_openalex(payload: dict) -> list[PaperMeta]:
    out = []
    for w in payload.get("results", []):
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        arxiv_id = None
        for loc in w.get("locations") or []:
            src = ((loc or {}).get("source") or {}).get("display_name") or ""
            url = (loc or {}).get("landing_page_url") or ""
            m = re.search(r"arxiv\.org/abs/([^v\s/]+)", url)
            if m and "arxiv" in (src.lower() + url):
                arxiv_id = m.group(1)
        oa = w.get("open_access") or {}
        out.append(PaperMeta(
            canonical_id=canonical_for(doi, arxiv_id, w.get("id", "")), title=w.get("title") or "",
            authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
            year=w.get("publication_year"), url=w.get("id"), provider="openalex", doi=doi, arxiv_id=arxiv_id,
            abstract=_openalex_abstract(w.get("abstract_inverted_index")),
            pdf_url=oa.get("oa_url") if (oa.get("oa_url") or "").lower().endswith(".pdf") else None,
        ))
    return out


class OpenAlexProvider:
    name = "openalex"
    API = "https://api.openalex.org/works"

    def __init__(self, timeout: float = 30, mailto: Optional[str] = None):
        self.timeout, self.mailto = timeout, mailto

    def search(self, query: str, max_results: int) -> list[PaperMeta]:
        params = {"search": query, "per-page": max_results}
        if self.mailto:
            params["mailto"] = self.mailto
        return parse_openalex(json.loads(_get(self.API, self.timeout, params=params)))

    def fetch_document(self, meta: PaperMeta, dest_dir: Path) -> Document:
        version = meta.doi or meta.canonical_id
        if not meta.pdf_url:
            return _unavailable(meta, version, "no open-access PDF location")
        try:
            data = _get(meta.pdf_url, self.timeout)
        except LiteratureError as exc:
            return _unavailable(meta, version, str(exc))
        return _document_from_pdf(meta.canonical_id, version, data, dest_dir)


# ------------------------------------------------------------------------------ local import
def _unavailable(meta: PaperMeta, version: str, note: str) -> Document:
    units = {"abstract": meta.abstract} if meta.abstract else {}
    return Document(canonical_id=meta.canonical_id, version=version, units=units,
                    status=TextStatus.abstract_only if units else TextStatus.unavailable,
                    sha256=sha256_bytes((meta.abstract or "").encode()), note=f"full text unavailable: {note}",
                    read_scope=["abstract"] if units else [])


def _document_from_pdf(canonical_id: str, version: str, data: bytes, dest_dir: Path) -> Document:
    digest = sha256_bytes(data)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{digest[:16]}.pdf"
    path.write_bytes(data)
    units, status, note = pdf_units(data)
    return Document(canonical_id=canonical_id, version=version, units=units, status=status, sha256=digest,
                    path=str(path), note=note)


def import_local(path: Path, dest_dir: Path, title: Optional[str] = None) -> tuple[PaperMeta, Document]:
    """Import a user-provided PDF / text / markdown file."""
    data = Path(path).read_bytes()
    digest = sha256_bytes(data)
    cid = f"local:{digest[:16]}"
    meta = PaperMeta(canonical_id=cid, title=title or Path(path).stem, authors=[], year=None,
                     url=None, provider="local_import")
    if Path(path).suffix.lower() == ".pdf":
        return meta, _document_from_pdf(cid, digest[:16], data, dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = dest_dir / f"{digest[:16]}{Path(path).suffix}"
    stored.write_bytes(data)
    return meta, Document(canonical_id=cid, version=digest[:16], units=text_units(data.decode("utf-8", "replace")),
                          status=TextStatus.full_text, sha256=digest, path=str(stored))


# ------------------------------------------------------------------------------ fixture
class FixtureLiteratureProvider:
    """Synthetic papers from ``tests/fixtures/literature/<task_id>.json``. Every id starts with
    ``fixture:`` and every record is marked synthetic; they exist only to test the flow."""
    name = "fixture"

    def __init__(self, root: Path, task_id: str):
        path = Path(root) / f"{task_id}.json"
        self.papers = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def search(self, query: str, max_results: int) -> list[PaperMeta]:
        words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
        scored = []
        for p in self.papers:
            hay = (p["title"] + " " + " ".join(p.get("keywords", []))).lower()
            score = sum(1 for w in words if w in hay)
            if score:
                scored.append((-score, p["canonical_id"], p))
        return [self._meta(p) for _, _, p in sorted(scored)[:max_results]]

    def _meta(self, p: dict) -> PaperMeta:
        return PaperMeta(canonical_id=p["canonical_id"], title=p["title"], authors=p.get("authors", []),
                         year=p.get("year"), url=None, provider="fixture", abstract=p.get("abstract"))

    def fetch_document(self, meta: PaperMeta, dest_dir: Path) -> Document:
        p = next(x for x in self.papers if x["canonical_id"] == meta.canonical_id)
        units = p.get("units", {})
        status = TextStatus(p.get("text_status", "partial_text"))
        return Document(canonical_id=p["canonical_id"], version=p.get("version", "fixture-v1"), units=units,
                        status=status, sha256=sha256_bytes(json.dumps(units, sort_keys=True).encode()),
                        note="synthetic fixture document")


# ------------------------------------------------------------------------------ user-supplied sources
def _html_units(html: str) -> dict[str, str]:
    import html as _html

    body = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    parts = re.split(r"(?i)<h[1-3][^>]*>", body)
    units: dict[str, str] = {}
    for i, part in enumerate(parts):
        text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", part))).strip()
        if text:
            units[f"§{i}"] = text
    return units


def resolve_user_source(source: str, dest_dir: Path, timeout: float = 30) -> tuple[PaperMeta, Document]:
    """Import a paper the user points to: an arXiv URL/id, a DOI, a PDF/HTML URL or a local file.
    Paywalled or failed downloads return an ``unavailable`` / abstract-only document."""
    path = Path(source).expanduser()
    if path.exists():
        return import_local(path, dest_dir)
    m = re.search(r"(?:arxiv\.org/(?:abs|pdf)/|^arxiv:)?(\d{4}\.\d{4,5})(v\d+)?", source)
    if m and ("arxiv" in source or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", source)):
        prov = ArxivProvider(timeout)
        hits = prov.by_id(m.group(1) + (m.group(2) or ""))
        if not hits:
            raise LiteratureError("UNAVAILABLE", f"arXiv id {m.group(1)} not found")
        return hits[0], prov.fetch_document(hits[0], dest_dir)
    doi = re.search(r"(10\.\d{4,9}/\S+)", source)
    if doi and not source.lower().endswith(".pdf"):
        prov2 = OpenAlexProvider(timeout)
        data = json.loads(_get(f"{OpenAlexProvider.API}/doi:{doi.group(1)}", timeout))
        metas = parse_openalex({"results": [data]})
        return metas[0], prov2.fetch_document(metas[0], dest_dir)
    if source.startswith(("http://", "https://")):
        data = _get(source, timeout)
        digest = sha256_bytes(data)
        cid = f"url:{digest[:16]}"
        meta = PaperMeta(canonical_id=cid, title=source, authors=[], year=None, url=source, provider="url_import")
        if data[:5] == b"%PDF-":
            return meta, _document_from_pdf(cid, digest[:16], data, dest_dir)
        units = _html_units(data.decode("utf-8", "replace"))
        status = TextStatus.partial_text if units else TextStatus.unavailable
        return meta, Document(canonical_id=cid, version=digest[:16], units=units, status=status, sha256=digest,
                              note="HTML page; section units split at headings")
    raise LiteratureError("UNAVAILABLE", f"cannot interpret source {source!r}")
