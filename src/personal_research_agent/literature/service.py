"""Literature service: budgeted search and reading with caching, de-duplication and logging.

* Papers are de-duplicated by canonical id (arXiv id / DOI / local hash / fixture id).
* Retrieved documents are saved as unit maps so that every evidence locator can be resolved.
* A cache hit costs no search budget but is logged; misses, retries and failures are charged.
* "Not retrieved" is recorded as such; it is never turned into "nobody has done this".
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from ..budget import Budget
from ..models import ExecutionOrigin, PaperRecord, TextStatus, VerificationStatus, canonical_json, utcnow
from ..store import Store
from .base import Document, LiteratureProvider, PaperMeta


def _safe(cid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", cid)


class LiteratureCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), isolation_level=None)
        self.conn.execute("CREATE TABLE IF NOT EXISTS search_cache (provider TEXT, query TEXT, max_results INTEGER,"
                          " fetched_at TEXT, json TEXT, PRIMARY KEY (provider, query, max_results))")

    def get(self, provider: str, query: str, n: int) -> Optional[list[dict]]:
        row = self.conn.execute("SELECT json FROM search_cache WHERE provider=? AND query=? AND max_results=?",
                                (provider, query, n)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, provider: str, query: str, n: int, hits: list[PaperMeta]) -> None:
        self.conn.execute("INSERT OR REPLACE INTO search_cache VALUES (?,?,?,?,?)",
                          (provider, query, n, utcnow(), json.dumps([h.__dict__ for h in hits])))


class LiteratureService:
    def __init__(self, provider: LiteratureProvider, store: Store, budget: Budget, run_dir: Path,
                 origin: ExecutionOrigin, cache: Optional[LiteratureCache] = None):
        self.provider, self.store, self.budget = provider, store, budget
        self.run_dir, self.origin, self.cache = run_dir, origin, cache
        self.sources_dir = run_dir / "sources"

    # ------------------------------------------------------------------ search
    def search(self, query: str, max_results: int, action_id: Optional[str], purpose: str) -> list[PaperRecord]:
        cached = self.cache.get(self.provider.name, query, max_results) if self.cache else None
        if cached is not None:
            hits = [PaperMeta(**h) for h in cached]
            self.store.event("literature_search", {"query": query, "provider": self.provider.name, "cache": "hit",
                                                   "purpose": purpose, "n": len(hits), "action_id": action_id})
        else:
            cost_type = "fixture" if self.origin == ExecutionOrigin.fixture else "measured"
            res = self.budget.reserve({"search_queries": 1}, action_id, cost_type=cost_type)
            started = time.time()
            try:
                hits = self.provider.search(query, max_results)
            except Exception as exc:
                self.budget.settle(res, {"search_queries": 1})
                self.store.event("literature_search_failed", {"query": query, "provider": self.provider.name,
                                                              "error": str(exc)[:300], "action_id": action_id})
                raise
            self.budget.settle(res, {"search_queries": 1})
            if self.cache and self.origin != ExecutionOrigin.fixture:
                self.cache.put(self.provider.name, query, max_results, hits)
            self.store.event("literature_search", {
                "query": query, "provider": self.provider.name, "cache": "miss", "purpose": purpose,
                "n": len(hits), "ids": [h.canonical_id for h in hits], "seconds": round(time.time() - started, 2),
                "action_id": action_id, "note": "absence of hits is not evidence of absence"})
        return [self.register(h) for h in hits]

    def register(self, meta: PaperMeta) -> PaperRecord:
        existing = [p for p in self.store.list(PaperRecord) if p.canonical_id == meta.canonical_id]
        if existing:
            self.store.event("paper_deduplicated", {"canonical_id": meta.canonical_id, "kept": existing[0].id})
            return existing[0]
        rec = PaperRecord(
            id=f"paper_{_safe(meta.canonical_id)}", origin=self.origin, source=f"literature:{meta.provider}",
            canonical_id=meta.canonical_id, title=meta.title, authors=meta.authors, year=meta.year,
            doi=meta.doi, arxiv_id=meta.arxiv_id, arxiv_version=meta.arxiv_version, url=meta.url,
            provider=meta.provider, abstract=meta.abstract,
            text_status=TextStatus.abstract_only if meta.abstract else TextStatus.unavailable,
            read_scope=[],
            verification_status=VerificationStatus.verified if self.origin == ExecutionOrigin.live else VerificationStatus.unverified,
        )
        self.store.put(rec, event="paper_registered", event_payload={"canonical_id": meta.canonical_id})
        return rec

    # ------------------------------------------------------------------ read
    def read(self, paper: PaperRecord, action_id: Optional[str]) -> tuple[PaperRecord, Document]:
        cached = self.load_document(paper)
        if cached is not None and paper.text_status in (TextStatus.full_text, TextStatus.partial_text):
            return paper, cached
        cost_type = "fixture" if self.origin == ExecutionOrigin.fixture else "measured"
        res = self.budget.reserve({"full_text_reads": 1}, action_id, cost_type=cost_type)
        meta = PaperMeta(canonical_id=paper.canonical_id, title=paper.title, authors=paper.authors, year=paper.year,
                         url=paper.url, provider=paper.provider, doi=paper.doi, arxiv_id=paper.arxiv_id,
                         arxiv_version=paper.arxiv_version, abstract=paper.abstract,
                         pdf_url=(f"https://arxiv.org/pdf/{paper.arxiv_id}{paper.arxiv_version or ''}"
                                  if paper.arxiv_id else None))
        try:
            doc = self.provider.fetch_document(meta, self.sources_dir)
        finally:
            self.budget.settle(res, {"full_text_reads": 1})
        doc_path = self.sources_dir / f"{_safe(paper.canonical_id)}.units.json"
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(canonical_json({"canonical_id": doc.canonical_id, "version": doc.version,
                                            "status": doc.status.value, "sha256": doc.sha256, "path": doc.path,
                                            "note": doc.note, "units": doc.units}), encoding="utf-8")
        paper = paper.model_copy(update={
            "text_status": doc.status, "document_path": str(doc_path.relative_to(self.run_dir)),
            "document_sha256": doc.sha256, "read_scope": [],      # retrieved, not yet read
            "arxiv_version": paper.arxiv_version or (doc.version if paper.arxiv_id else None),
        })
        self.store.update(paper, event="paper_read", event_payload={
            "text_status": doc.status.value, "units": len(doc.units), "note": doc.note, "action_id": action_id})
        return paper, doc

    def import_source(self, source: str, action_id: Optional[str] = None) -> PaperRecord:
        """User-provided DOI / arXiv URL / paper URL / local file. Counts as one full-text read."""
        from .providers import resolve_user_source

        res = self.budget.reserve({"full_text_reads": 1}, action_id)
        try:
            meta, doc = resolve_user_source(source, self.sources_dir)
        finally:
            self.budget.settle(res, {"full_text_reads": 1})
        paper = self.register(meta)
        doc_path = self.sources_dir / f"{_safe(paper.canonical_id)}.units.json"
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(canonical_json({"canonical_id": doc.canonical_id, "version": doc.version,
                                            "status": doc.status.value, "sha256": doc.sha256, "path": doc.path,
                                            "note": doc.note, "units": doc.units}), encoding="utf-8")
        paper = paper.model_copy(update={"text_status": doc.status, "document_path": str(doc_path.relative_to(self.run_dir)),
                                         "document_sha256": doc.sha256, "read_scope": sorted(doc.units),
                                         "verification_status": VerificationStatus.verified
                                         if doc.status != TextStatus.unavailable else paper.verification_status})
        self.store.update(paper, event="paper_imported", event_payload={"source": source, "status": doc.status.value,
                                                                        "units": len(doc.units)})
        return paper

    def load_document(self, paper: PaperRecord) -> Optional[Document]:
        if not paper.document_path:
            return None
        path = self.run_dir / paper.document_path
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return Document(canonical_id=d["canonical_id"], version=d["version"], units=d["units"],
                        status=TextStatus(d["status"]), sha256=d["sha256"], path=d.get("path"), note=d.get("note"))


def load_document_for(run_dir: Path, paper: PaperRecord) -> Optional[Document]:
    if not paper.document_path:
        return None
    path = run_dir / paper.document_path
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return Document(canonical_id=d["canonical_id"], version=d["version"], units=d["units"],
                    status=TextStatus(d["status"]), sha256=d["sha256"], path=d.get("path"), note=d.get("note"))
