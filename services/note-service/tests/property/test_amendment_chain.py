"""Sprint-08 day-4 — chain integrity property test.

Hypothesis generates random ``ChainNode`` sequences modelling the
sprint-08 append-only versioning rules. For *valid* generated histories
(those produced by our model of an append + amend), the verifier MUST
note zero anomalies. For *injected* corruptions (cycle, gap, etc.),
the verifier MUST flag exactly the expected anomaly kind.

Runs in CI as part of ``services/note-service/tests/property``. The
chain reconciler (day-8) runs the same verifier daily against
production data.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from note_service.domain.chain_integrity import ChainNode, verify_chain

# ── Strategy: generate a *valid* history ────────────────────────────


@st.composite
def valid_chain(draw):
    """Generate a history that mimics POST /notes + N draft updates
    + optional finalize + optional amendments off the finalized head.

    Invariants by construction:
    - version_number runs 1..N contiguously.
    - non-amendment versions chain parent = previous version.
    - amendments only appear after the finalized version, with parent =
      the previous head.
    """
    n_total = draw(st.integers(min_value=1, max_value=12))
    n_pre_final = draw(st.integers(min_value=1, max_value=n_total))
    nodes: list[ChainNode] = []
    ids: list[UUID] = []
    for i in range(1, n_total + 1):
        nid = uuid4()
        ids.append(nid)
        if i == 1:
            nodes.append(
                ChainNode(
                    id=nid,
                    version_number=i,
                    parent_id=None,
                    is_amendment=False,
                )
            )
        elif i <= n_pre_final:
            nodes.append(
                ChainNode(
                    id=nid,
                    version_number=i,
                    parent_id=ids[i - 2],
                    is_amendment=False,
                )
            )
        else:
            # Amendment off the previous head — this matches the
            # production router which always uses current_version_id
            # (the head) as parent_version_id.
            parent = ids[i - 2]  # previous version's id
            nodes.append(
                ChainNode(
                    id=nid,
                    version_number=i,
                    parent_id=parent,
                    is_amendment=True,
                )
            )
    return nodes, ids


# ── Tests ───────────────────────────────────────────────────────────


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(history=valid_chain())
def test_valid_history_produces_no_anomalies(history):
    nodes, _ids = history
    head = nodes[-1].id
    anomalies = verify_chain(nodes, current_version_id=head)
    assert anomalies == [], anomalies


def test_gap_detected():
    a, b = uuid4(), uuid4()
    nodes = [
        ChainNode(id=a, version_number=1, parent_id=None, is_amendment=False),
        ChainNode(id=b, version_number=3, parent_id=a, is_amendment=False),
    ]
    anomalies = verify_chain(nodes, current_version_id=b)
    assert any(a.kind == "gap_in_version_numbers" for a in anomalies)


def test_cycle_detected():
    a, b = uuid4(), uuid4()
    nodes = [
        ChainNode(id=a, version_number=1, parent_id=b, is_amendment=False),
        ChainNode(id=b, version_number=2, parent_id=a, is_amendment=False),
    ]
    anomalies = verify_chain(nodes, current_version_id=b)
    assert any(a.kind == "cycle_detected" for a in anomalies)


def test_parent_missing_flagged():
    a = uuid4()
    nodes = [
        # Genesis has parent_id pointing at something that doesn't exist.
        ChainNode(id=a, version_number=1, parent_id=uuid4(), is_amendment=False),
    ]
    anomalies = verify_chain(nodes, current_version_id=a)
    assert any(a.kind == "parent_missing" for a in anomalies)


def test_unreachable_from_head_flagged():
    a, b, isolated = uuid4(), uuid4(), uuid4()
    nodes = [
        ChainNode(id=a, version_number=1, parent_id=None, is_amendment=False),
        ChainNode(id=b, version_number=2, parent_id=a, is_amendment=False),
        # Pretend version_number=3 exists but isn't reachable from head=b.
        ChainNode(id=isolated, version_number=3, parent_id=a, is_amendment=False),
    ]
    anomalies = verify_chain(nodes, current_version_id=b)
    # Note: version 3 is reachable from itself but walking from head b
    # only sees {b, a}. So 'isolated' (3) is unreachable from head.
    assert any(a.kind == "unreachable_from_head" for a in anomalies)
