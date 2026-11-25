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
# A class name in a query: an identifier with an uppercase letter, optionally
# dotted (``ComplexConstant``, ``Modelica.Blocks.Sources.Sine``).
_CLASS_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_MSL_URL = re.compile(r"modelica://([^/]+)/(.+?)(?:-\d+)?$")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, with camelCase split so Modelica identifiers
    like ``CylinderDouble`` also match ``cylinder``/``double``."""
    text = _CAMEL.sub(" ", text)
    return _TOKEN.findall(text.lower())


def class_names(text: str) -> list[str]:
    """Words in a query that can only be class names: dotted, or CamelCase
    (``ComplexConstant``, ``LimPID``). A plain capitalized word may just start
    a sentence, and a lowerCamel word is usually a language keyword or operator."""
    return [w for w in _CLASS_NAME.findall(text)
            if "." in w or (w[0].isupper() and any(c.isupper() for c in w[1:]))]


def msl_parts(url: str):
    """``(top package, class name)`` of an MSL pseudo-URL, or None."""
    m = _MSL_URL.match(url)
    return (m.group(1), m.group(2)) if m else None


def resolve_corpora(name: str) -> tuple[str, ...]:
    key = (name or "all").lower()
    if key not in ALIASES:
        raise ValueError(
            f"unknown corpus '{name}'. choose from: {', '.join(ALIASES)}"
        )
    return ALIASES[key]


def _read_corpus(corpus):
    """Load ``<corpus>.json``, or merge ``<corpus>.part1.json``, ``.part2.json``, ...

    Large corpora are split into parts to keep each file under upload size
    limits; parts are merged in numeric order so document order is unchanged.
    """
    single = os.path.join(DATA_DIR, f"{corpus}.json")
    if os.path.exists(single):
        paths = [single]
    else:
        prefix = f"{corpus}.part"
        nums = sorted(
            int(name[len(prefix):-5])
            for name in os.listdir(DATA_DIR)
            if name.startswith(prefix) and name.endswith(".json")
            and name[len(prefix):-5].isdigit()
        )
        paths = [os.path.join(DATA_DIR, f"{prefix}{n}.json") for n in nums]
        if not paths:
            raise FileNotFoundError(
                f"no data for corpus '{corpus}': expected {corpus}.json "
                f"or {corpus}.part1.json, ... in {DATA_DIR}"
            )
    data = {}
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data.update(json.load(fh))
    return data


class Index:
    def __init__(self, corpora=CORPORA):
        self.docs = []          # list of {id, corpus, url, title, text, len}
        self.postings = defaultdict(list)   # term -> [(doc_idx, tf), ...]
        self.df = defaultdict(int)          # term -> document frequency
        self.idf = {}
        self.avgdl = 0.0
        self.by_class = defaultdict(list)   # MSL class name -> [doc_idx, ...]
        self._load(corpora)
        self._build()

    def _load(self, corpora):
        for corpus in corpora:
            data = _read_corpus(corpus)
            for url, text in data.items():
                title = text.lstrip().split("\n", 1)[0].lstrip("# ").strip()
                parts = msl_parts(url) if corpus == "msl" else None
                if parts:
                    self.by_class[parts[1]].append(len(self.docs))
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
        # In a library-only search, a class named exactly in the query ranks
        # first: BM25 alone lets longer chunks that merely mention its words
        # outrank the class itself. Mixed searches are left alone, where such
        # names usually ask about the language or the tool instead.
        named = [d["id"] for d in self.find_class_all(query)] \
            if allow == {"msl"} else []
        if named:
            top = max(scores.values(), default=0.0)
            for i in named:
                scores[i] += top
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [(self.docs[i], s) for i, s in ranked]

    def find_class(self, name: str):
        """MSL entries for a class name, leaf (``Brake``) or dotted
        (``Modelica.Mechanics.Translational.Components.Brake``). Entries record
        only the top-level package, so a dotted name narrows by that alone."""
        leaf = name.rsplit(".", 1)[-1]
        hits = [self.docs[i] for i in self.by_class.get(leaf, [])]
        if "." in name:
            hits = [d for d in hits
                    if name.startswith(msl_parts(d["url"])[0] + ".")] or hits
        return hits

    def find_class_all(self, query: str):
        return [d for name in class_names(query) for d in self.find_class(name)]

    def get(self, url: str):
        for doc in self.docs:
            if doc["url"] == url:
                return doc
        return None
