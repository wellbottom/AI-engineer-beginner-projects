"""Property-based tests for ``ai_shared.config.load_settings`` validation.

# Feature: ai-engineer-practice-monorepo, Property 32: startup config loading fails iff a required variable is absent and the reported names equal exactly the absent required variables (incl. DB_*)

**Validates: Requirements 3.9, 3.13**
"""

from __future__ import annotations

import contextlib
import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import ai_shared.config as config
from ai_shared import load_settings
from ai_shared.errors import MissingConfigError

KNOWN = list(config.KNOWN_ENV_VARS)


@contextlib.contextmanager
def patched_env(present: dict[str, str]):
    """Set exactly ``present`` for the known vars; clear the rest; then restore.

    ``isolated_env`` (autouse) already cleared known vars and disabled real
    ``.env`` discovery, but Hypothesis re-runs the test body many times within a
    single fixture lifetime, so each example must clean up after itself.
    """
    saved = {k: os.environ.get(k) for k in KNOWN}
    try:
        for k in KNOWN:
            os.environ.pop(k, None)
        for k, v in present.items():
            os.environ[k] = v
        yield
    finally:
        for k in KNOWN:
            os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# Non-whitespace value alphabet so any min_size>=1 string is non-empty after strip.
_VALUE_TEXT = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./:",
    min_size=1,
    max_size=12,
)


@st.composite
def scenarios(draw):
    """Generate a (required, present) scenario over the known env universe.

    - ``required`` is a list sampled from the known universe and may contain
      duplicates / overlapping names (exercising the set-dedup contract).
    - ``present`` maps a random subset of known vars to either an empty string
      (counts as absent) or a non-empty value. ``DB_PORT`` non-empty values are
      kept integer-valued so we exercise only the presence/absence contract here
      (the non-integer ``DB_PORT`` path is covered by a dedicated example test).
    """
    required = draw(
        st.lists(st.sampled_from(KNOWN), min_size=0, max_size=len(KNOWN) * 2)
    )

    present: dict[str, str] = {}
    for name in KNOWN:
        choice = draw(st.sampled_from(["absent", "empty", "value"]))
        if choice == "empty":
            present[name] = ""
        elif choice == "value":
            if name == "DB_PORT":
                present[name] = str(draw(st.integers(min_value=1, max_value=65535)))
            else:
                present[name] = draw(_VALUE_TEXT)
        # "absent": leave the variable unset
    return required, present


@settings(max_examples=200, deadline=None)
@given(scenarios())
def test_load_settings_fails_iff_required_var_absent(scenario):
    required, present = scenario

    # Oracle: a required variable is "absent" iff it has no default AND it was not
    # provided with a non-empty value. Variables with defaults are never absent.
    present_nonempty = {k for k, v in present.items() if v.strip()}
    expected_missing = sorted(
        {r for r in required if r not in config.DEFAULTS and r not in present_nonempty}
    )

    with patched_env(present):
        if expected_missing:
            with pytest.raises(MissingConfigError) as exc_info:
                load_settings(required)
            # Reported names equal EXACTLY the absent required variables.
            assert sorted(exc_info.value.names) == expected_missing
        else:
            settings_obj = load_settings(required)
            # Success path: every required variable resolved to a non-empty value.
            assert settings_obj is not None
