"""Source revision fingerprints: SHA-256 over normalized section content."""
from __future__ import annotations

import hashlib


def fingerprint_text(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fingerprint_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
