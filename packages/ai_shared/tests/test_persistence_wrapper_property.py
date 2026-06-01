"""Property-based test for the persistence-failure wrapper (Property 34).

# Feature: ai-engineer-practice-monorepo, Property 34: any injected persistence outcome leaves the result unchanged and sets ok/operation_id correctly (done event for streams)

**Validates: Requirements 12.4**

For any completed operation and any injected persistence outcome (a stub
``HistoryRepository`` that either succeeds or raises :class:`PersistenceError`):

- the operation result returned to the user is **unchanged** in both cases;
- the persistence indication is ``ok = True`` on success and
  ``ok = False`` carrying an ``operation_id`` on failure;
- for the streamed shape the indication rides on the terminal ``done`` event
  payload — it never converts the successful stream into an ``error`` event.
"""

from __future__ import annotations

import copy
import itertools

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.errors import PersistenceError
from ai_shared.history import ProjectId
from ai_shared.persistence import persist_record


class _StubRepo:
    """A repository stub whose ``save_record`` succeeds or raises on demand."""

    def __init__(self, *, should_fail: bool, saved_id: int = 1) -> None:
        self.should_fail = should_fail
        self.saved_id = saved_id
        self.calls: list[tuple] = []

    def save_record(self, project, record):  # noqa: ANN001 - stub signature
        self.calls.append((project, record))
        if self.should_fail:
            raise PersistenceError(reason="injected failure")
        return self.saved_id


# A deterministic operation_id factory so failure assertions are stable.
def _seq_factory():
    counter = itertools.count(1)
    return lambda: f"op-{next(counter)}"


# Arbitrary JSON-able operation results (the "result returned to the user").
_json_scalars = st.none() | st.booleans() | st.integers() | st.text(max_size=20)
_result_bodies = st.dictionaries(
    keys=st.text(min_size=1, max_size=10).filter(lambda k: k != "persistence"),
    values=_json_scalars | st.lists(_json_scalars, max_size=4),
    max_size=6,
)


@settings(max_examples=200, deadline=None)
@given(should_fail=st.booleans(), body=_result_bodies, project=st.sampled_from(list(ProjectId)))
def test_persist_record_non_streamed_body(should_fail, body, project):
    repo = _StubRepo(should_fail=should_fail)
    record = object()  # build_history_record output is opaque to the wrapper
    original = copy.deepcopy(body)

    outcome = persist_record(
        repo, project, record, operation_id_factory=_seq_factory()
    )
    merged = outcome.attach_to_body(body)

    # 1) The operation result is unchanged: every original key/value survives and
    #    the source dict was not mutated.
    assert body == original
    for key, value in original.items():
        assert merged[key] == value

    # 2) The persistence indication is correct.
    if should_fail:
        assert outcome.ok is False
        assert merged["persistence"]["ok"] is False
        assert isinstance(merged["persistence"]["operation_id"], str)
        assert merged["persistence"]["operation_id"]
    else:
        assert outcome.ok is True
        assert merged["persistence"] == {"ok": True}
        assert "operation_id" not in merged["persistence"]
        assert outcome.saved_id == repo.saved_id


@settings(max_examples=200, deadline=None)
@given(
    should_fail=st.booleans(),
    usage=st.dictionaries(st.sampled_from(["prompt_tokens", "output_tokens", "total_tokens"]), st.integers(min_value=0, max_value=9999), max_size=3),
    project=st.sampled_from(list(ProjectId)),
)
def test_persist_record_streamed_done_event(should_fail, usage, project):
    repo = _StubRepo(should_fail=should_fail)
    record = object()
    # The done payload already carries success metadata (e.g. token usage); the
    # persistence indication must ride alongside it, not replace it.
    done_payload = {"usage": dict(usage)}
    original_done = copy.deepcopy(done_payload)

    outcome = persist_record(
        repo, project, record, operation_id_factory=_seq_factory()
    )
    done = outcome.attach_to_done(done_payload)

    # 1) Existing terminal-success metadata is preserved (stream not converted to
    #    an error; this is still a `done` event).
    assert done["usage"] == original_done["usage"]

    # 2) The persistence indication rides on the done payload.
    if should_fail:
        assert done["persistence"]["ok"] is False
        assert isinstance(done["persistence"]["operation_id"], str)
        assert done["persistence"]["operation_id"]
    else:
        assert done["persistence"] == {"ok": True}


@pytest.mark.parametrize("should_fail", [True, False])
def test_failure_is_logged_with_operation_id(should_fail, caplog):
    """On failure the wrapper logs the failure with the same operation_id it returns.

    Plain parametrized (not Hypothesis) because it asserts on the function-scoped
    ``caplog`` fixture, which must reset per case — and the input space here is just
    the two boolean outcomes.
    """
    import logging

    repo = _StubRepo(should_fail=should_fail)
    with caplog.at_level(logging.ERROR, logger="ai_shared.persistence"):
        outcome = persist_record(
            repo, ProjectId.PLAYGROUND, object(), operation_id_factory=lambda: "op-xyz"
        )

    if should_fail:
        assert outcome.operation_id == "op-xyz"
        assert any("op-xyz" in rec.getMessage() for rec in caplog.records)
    else:
        assert outcome.operation_id is None
        assert not caplog.records
