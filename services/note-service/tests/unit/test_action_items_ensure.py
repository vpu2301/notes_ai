"""``ensure_items`` derives a version's items on first read (0042) and
never re-parses a version that already has them."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from note_service.domain import action_items
from note_service.domain import action_items_repository as items_repo


@pytest.mark.asyncio
async def test_first_read_materialises_then_reuses(monkeypatch: pytest.MonkeyPatch) -> None:
    version_id = uuid4()
    note = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    version = SimpleNamespace(
        id=version_id,
        content=SimpleNamespace(
            sections=[SimpleNamespace(section_key="action_items", text="- Anna: send deck")]
        ),
    )
    stored: list[items_repo.ItemRow] = []
    inserts: list[int] = []

    async def _fetch_items(conn, *, version_id):  # noqa: ANN001
        return list(stored)

    async def _latest_statuses(conn, *, note_id, keys, before_version_id):  # noqa: ANN001
        return {}

    async def _insert_items(conn, *, tenant_id, note_id, version_id, items, statuses):  # noqa: ANN001
        inserts.append(len(items))
        for i, p in enumerate(items):
            stored.append(
                items_repo.ItemRow(
                    id=uuid4(),
                    note_id=note_id,
                    note_version_id=version_id,
                    item_key=p.item_key,
                    position=i,
                    text=p.text,
                    owner_label=p.owner_label,
                    owner_confidence=p.owner_confidence,
                    due_date=p.due_date,
                    due_text=p.due_text,
                    due_confidence=p.due_confidence,
                    status="open",
                )
            )
        return len(items)

    async def _anchor(conn, *, tenant_id):  # noqa: ANN001
        return date(2026, 9, 17)

    monkeypatch.setattr(items_repo, "fetch_items", _fetch_items)
    monkeypatch.setattr(items_repo, "latest_statuses", _latest_statuses)
    monkeypatch.setattr(items_repo, "insert_items", _insert_items)
    monkeypatch.setattr(action_items, "anchor_date", _anchor)

    first = await action_items.ensure_items(None, note=note, version=version)  # type: ignore[arg-type]
    assert [i.text for i in first] == ["send deck"]
    second = await action_items.ensure_items(None, note=note, version=version)  # type: ignore[arg-type]
    assert second == first
    assert inserts == [1]


@pytest.mark.asyncio
async def test_no_action_lines_means_no_items(monkeypatch: pytest.MonkeyPatch) -> None:
    version = SimpleNamespace(id=uuid4(), content=SimpleNamespace(sections=[]))
    note = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    async def _fetch_items(conn, *, version_id):  # noqa: ANN001
        return []

    async def _anchor(conn, *, tenant_id):  # noqa: ANN001
        return date(2026, 9, 17)

    monkeypatch.setattr(items_repo, "fetch_items", _fetch_items)
    monkeypatch.setattr(action_items, "anchor_date", _anchor)
    assert await action_items.ensure_items(None, note=note, version=version) == []  # type: ignore[arg-type]
