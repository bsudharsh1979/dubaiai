"""Knowledge loading and retrieval.

SOP markdown files are split into sections (``## S1 ...``) and stored with document
id, version, section and access roles.  Retrieval applies the authorization filter
*before* scoring.  Lexical retrieval (BM25-like) is always available and labelled
``lexical``; when an embedding provider is configured and embeddings are stored,
cosine similarity over stored vectors is used and labelled ``embedding``.  Optional
reranking is a separate labelled step.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import SOP_DIR
from ..models import Document

TOKEN = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text) if len(t) > 1]


def parse_sop(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path} missing front matter")
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    body = m.group(2)
    roles = [r.strip() for r in meta.get("access_roles", "").split(",") if r.strip()]
    sections = []
    for sec in re.split(r"\n(?=## )", body):
        sm = re.match(r"## (\S+) (.*?)\n(.*)", sec.strip(), re.S)
        if not sm:
            continue
        sid, title, sbody = sm.group(1), sm.group(2).strip(), sm.group(3).strip()
        sections.append({"id": f"{meta['doc_id']}#{sid}@{meta['version']}", "doc_id": meta["doc_id"], "version": meta["version"], "section": sid,
                         "title": f"{meta['title']} — {title}", "collection": meta["collection"], "access_roles": roles, "body": sbody})
    return sections


def load_all(db: Session) -> int:
    n = 0
    for p in sorted(SOP_DIR.glob("*.md")):
        for sec in parse_sop(p):
            if db.get(Document, sec["id"]) is None:
                db.add(Document(**sec))
                n += 1
    db.flush()
    return n


def _bm25(query_tokens: list[str], docs: list[tuple[Document, list[str]]], k1: float = 1.5, b: float = 0.75) -> list[tuple[float, Document]]:
    N = len(docs)
    avgdl = sum(len(t) for _, t in docs) / max(N, 1)
    df = Counter()
    for _, toks in docs:
        for t in set(toks):
            df[t] += 1
    scored = []
    for d, toks in docs:
        tf = Counter(toks)
        score = 0.0
        for q in query_tokens:
            if q not in tf:
                continue
            idf = math.log(1 + (N - df[q] + 0.5) / (df[q] + 0.5))
            score += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(toks) / max(avgdl, 1)))
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    return scored


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db_ = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db_)


def retrieve(db: Session, query: str, roles: list[str], collection: str | None = None, k: int = 3, query_embedding: list[float] | None = None) -> list[dict]:
    q = select(Document)
    if collection:
        q = q.where(Document.collection == collection)
    rows = db.execute(q).scalars().all()
    # Authorization filter first.
    roleset = set(roles)
    allowed = [d for d in rows if not d.access_roles or (roleset & set(d.access_roles))]
    if not allowed:
        return []
    method = "lexical"
    if query_embedding is not None and all(d.embedding for d in allowed):
        scored = sorted(((_cosine(query_embedding, d.embedding), d) for d in allowed), key=lambda x: -x[0])
        method = "embedding"
    else:
        scored = _bm25(tokenize(query), [(d, tokenize(d.title + " " + d.body)) for d in allowed])
    out = []
    for score, d in scored[:k]:
        out.append({"doc_id": d.doc_id, "version": d.version, "section": d.section, "title": d.title, "collection": d.collection, "score": round(float(score), 3),
                    "excerpt": d.body[:600], "citation": f"{d.doc_id} v{d.version} §{d.section}", "method": method, "label": "demonstration procedure — not official policy"})
    return out
