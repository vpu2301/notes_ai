"""Per-tenant prefix→top-K map built from the phrase corpus (dict-based; marisa-trie if it outgrows memory)."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

MAX_PREFIX_LEN = 6
TOP_K_PER_PREFIX = 20


def normalize(text: str) -> str:
    """NFC + lowercase, applied identically at build and lookup (decomposed Cyrillic must match)."""
    return unicodedata.normalize("NFC", text).lower()


@dataclass(frozen=True, slots=True)
class PhraseTrieEntry:
    id: str
    phrase: str
    source: str
    impression_count: int
    acceptance_count: int
    last_accepted_at: datetime | None


@dataclass(slots=True)
class TenantTrie:
    """Prefix→top-K-candidates map, cached in Redis per (tenant, language, user)."""

    tenant_id: str
    language: str
    user_id: str
    # Lower-cased prefix (length 1..MAX_PREFIX_LEN) → ordered list of entry ids
    prefix_to_ids: dict[str, list[str]]
    entries: dict[str, PhraseTrieEntry]
    built_at_unix: float

    def candidates_for(self, prefix: str, *, k: int = TOP_K_PER_PREFIX) -> list[PhraseTrieEntry]:
        if not prefix:
            return []
        norm = normalize(prefix)
        key = norm[:MAX_PREFIX_LEN]
        ids = self.prefix_to_ids.get(key)
        if not ids:
            # No bucket (e.g. prefix > MAX_PREFIX_LEN): scan entries.
            out: list[PhraseTrieEntry] = []
            for e in self.entries.values():
                if normalize(e.phrase).startswith(norm):
                    out.append(e)
                    if len(out) >= k * 2:
                        break
            return out[:k]
        return [self.entries[i] for i in ids[:k] if i in self.entries]


def build_trie_from_phrases(
    *,
    tenant_id: str,
    language: str,
    user_id: str,
    rows: Iterable[PhraseTrieEntry],
) -> TenantTrie:
    entries: dict[str, PhraseTrieEntry] = {}
    by_prefix: dict[str, list[tuple[str, float]]] = {}

    for e in rows:
        entries[e.id] = e
        # Coarse bucket score; the full ranker refines later.
        coarse = (
            {"user": 1.0, "tenant": 0.6, "system": 0.3}.get(e.source, 0.3)
            * (e.acceptance_count + 1)
            / (e.impression_count + 10)
        )
        phrase_norm = normalize(e.phrase)
        for length in range(1, min(MAX_PREFIX_LEN, len(phrase_norm)) + 1):
            key = phrase_norm[:length]
            by_prefix.setdefault(key, []).append((e.id, coarse))

    prefix_to_ids: dict[str, list[str]] = {}
    for k, lst in by_prefix.items():
        lst.sort(key=lambda x: x[1], reverse=True)
        prefix_to_ids[k] = [eid for eid, _ in lst[:TOP_K_PER_PREFIX]]

    return TenantTrie(
        tenant_id=tenant_id,
        language=language,
        user_id=user_id,
        prefix_to_ids=prefix_to_ids,
        entries=entries,
        built_at_unix=datetime.now(UTC).timestamp(),
    )
