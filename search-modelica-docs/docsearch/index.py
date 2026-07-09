"""Pure-stdlib BM25 index over the bundled documentation corpora.

No third-party dependencies. Loads the prebuilt url->text JSON files in
``data/`` and scores documents with Okapi BM25. Corpora:

    spec  - Modelica Language Spec        (the language, normative)
    docs  - Wolfram System Modeler docs   (the tool)
    msl   - Modelica Standard Library     (class docs + stripped source)

Aliases used by the CLI:
    modelica      = spec
    systemmodeler = docs
    library       = msl
    all           = spec + docs + msl
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

CORPORA = ("spec", "docs", "msl")

CORPUS_LABEL = {
    "spec": "Modelica Language Specification",
    "docs": "Wolfram System Modeler Documentation",
    "msl": "Modelica Standard Library (MSL) Reference",
}

# CLI alias -> set of base corpora
ALIASES = {
    "all": ("spec", "docs", "msl"),
    "modelica": ("spec",),
    "systemmodeler": ("docs",),
    "sm": ("docs",),
    "library": ("msl",),
    "spec": ("spec",),
    "docs": ("docs",),
    "msl": ("msl",),
}

# BM25 hyperparameters (standard defaults).
K1 = 1.5
B = 0.75
# Extra weight for the section-title / header-path tokens (strong topic signal).
TITLE_BOOST = int(os.environ.get("DOCSEARCH_TITLE_BOOST", "2"))

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, with camelCase split so Modelica identifiers
    like ``CylinderDouble`` also match ``cylinder``/``double``."""
    text = _CAMEL.sub(" ", text)
    return _TOKEN.findall(text.lower())


def resolve_corpora(name: str) -> tuple[str, ...]:
    key = (name or "all").lower()
    if key not in ALIASES:
        raise ValueError(
            f"unknown corpus '{name}'. choose from: {', '.join(ALIASES)}"
        )
    return ALIASES[key]


class Index:
    def __init__(self, corpora=CORPORA):
        self.docs = []          # list of {id, corpus, url, title, text, len}
        self.postings = defaultdict(list)   # term -> [(doc_idx, tf), ...]
        self.df = defaultdict(int)          # term -> document frequency
        self.idf = {}
        self.avgdl = 0.0
        self._load(corpora)
        self._build()

    def _load(self, corpora):
        for corpus in corpora:
            path = os.path.join(DATA_DIR, f"{corpus}.json")
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for url, text in data.items():
                title = text.lstrip().split("\n", 1)[0].lstrip("# ").strip()
                self.docs.append(
                    {
                        "id": len(self.docs),
                        "corpus": corpus,
                        "url": url,
                        "title": title,
                        "text": text,
                    }
                )

    def _build(self):
        total_len = 0
        for doc in self.docs:
            toks = tokenize(doc["text"])
            if TITLE_BOOST > 1:
                toks = toks + tokenize(doc["title"]) * (TITLE_BOOST - 1)
            doc["len"] = len(toks)
            total_len += len(toks)
            tf = defaultdict(int)
            for t in toks:
                tf[t] += 1
            for t, c in tf.items():
                self.postings[t].append((doc["id"], c))
                self.df[t] += 1
        n = max(len(self.docs), 1)
        self.avgdl = total_len / n
        for t, df in self.df.items():
            self.idf[t] = math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, corpora=None, k: int = 5):
        allow = set(corpora) if corpora else None
        scores = defaultdict(float)
        for t in set(tokenize(query)):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for doc_id, tf in self.postings[t]:
                doc = self.docs[doc_id]
                if allow is not None and doc["corpus"] not in allow:
                    continue
                dl = doc["len"]
                denom = tf + K1 * (1 - B + B * dl / self.avgdl)
                scores[doc_id] += idf * (tf * (K1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [(self.docs[i], s) for i, s in ranked]

    def get(self, url: str):
        for doc in self.docs:
            if doc["url"] == url:
                return doc
        return None
