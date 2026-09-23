"""엔티티 ID 규칙: `<type prefix>:<slug>` (예: person:plato, concept:justice)."""
from __future__ import annotations

import hashlib
import re

from . import ontology as O


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", text.strip().lower(), flags=re.UNICODE).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not s or not s.isascii():
        # 비 ASCII 라벨은 짧은 해시를 덧붙여 충돌을 피한다
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        s = (re.sub(r"[^a-z0-9\-]", "", s)[:24] or "x") + "-" + h
    return s[:64]


def make_id(type_name: str, label: str) -> str:
    return f"{O.ENTITY_TYPES[type_name].prefix}:{slugify(label)}"
