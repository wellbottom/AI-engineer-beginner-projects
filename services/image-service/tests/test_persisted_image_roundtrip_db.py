"""DB-backed property test: persisted image bytes round-trip (Property 35).

# Feature: ai-engineer-practice-monorepo, Property 35: persisting then retrieving image bytes yields exactly the original bytes and MIME type

**Validates: Requirements 12.9**

For any generated image bytes and their MIME type, persisting them to the **real**
Database (as ``BYTEA``) via the shared :class:`HistoryRepository` and then retrieving
the record yields **exactly** the original bytes and the same MIME type — so a
reopened history record decodes to the original image. The flow mirrors what
``POST /generate`` does on success:
``ImageGenerationResult -> build_history_record -> save_record -> get_record``.

The retrieved bytes are additionally pushed through the service's own
:func:`app.codec.encode_image` / :func:`app.codec.decode_image` (the history-detail
re-emit path) to prove the durable bytes round-trip back to the original through the
web-renderable payload too.

The test SKIPS cleanly when no PostgreSQL is reachable (see ``db_utils``), so it
never hangs or hard-fails without a database; the orchestrator runs it against the
ephemeral ``postgres`` provided via ``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from ai_shared.db import dispose_engine, get_engine, get_sessionmaker
from ai_shared.history import (
    HistoryRepository,
    ImageGenerationResult,
    ImageRecord,
    ProjectId,
    build_history_record,
)
from ai_shared.models import Base, ImageHistory

from app.codec import WEB_RENDERABLE_MIME_TYPES, decode_image, encode_image

from . import db_utils

pytestmark = pytest.mark.skipif(
    not db_utils.database_reachable(), reason=db_utils.SKIP_REASON
)

# Only the image table is touched; truncated between examples to keep DB state
# independent across Hypothesis examples.
_IMAGE_TABLE = ImageHistory.__tablename__


@pytest.fixture(scope="module")
def repo():
    """Module-scoped HistoryRepository against the ephemeral DB (schema created once)."""
    settings_obj = db_utils.test_settings()
    engine = get_engine(settings_obj)
    Base.metadata.create_all(engine)
    repository = HistoryRepository(get_sessionmaker(settings_obj))
    yield engine, repository
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_IMAGE_TABLE} RESTART IDENTITY CASCADE"))
    dispose_engine(settings_obj)


# Image bytes across the space: empty, arbitrary blobs (all byte values incl. 0x00),
# and a large all-byte-values blob to exercise BYTEA at size.
_image_bytes = st.one_of(
    st.just(b""),
    st.binary(max_size=4096),
    st.just(bytes(range(256)) * 64),  # 16 KB, every byte value
)
# Only PNG is produced by the service, but Property 35 asserts the stored MIME type
# round-trips exactly, so sample across the web-renderable set.
_mime_types = st.sampled_from(sorted(WEB_RENDERABLE_MIME_TYPES))
# Prompt/model are also persisted columns; include unicode + whitespace.
_prompts = st.text(min_size=1, max_size=120)
_models = st.sampled_from(
    [
        "stabilityai/stable-diffusion-xl-base-1.0",
        "black-forest-labs/FLUX.1-schnell",
        "runwayml/stable-diffusion-v1-5",
    ]
)


# Feature: ai-engineer-practice-monorepo, Property 35: persisting then retrieving image bytes yields exactly the original bytes and MIME type
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(image_bytes=_image_bytes, mime_type=_mime_types, prompt=_prompts, model=_models)
def test_persisted_image_bytes_and_mime_roundtrip_exactly(
    repo, image_bytes: bytes, mime_type: str, prompt: str, model: str
) -> None:
    engine, repository = repo

    # Clean slate for this example.
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_IMAGE_TABLE} RESTART IDENTITY CASCADE"))

    # Persist exactly as POST /generate does on success.
    record = build_history_record(
        ProjectId.IMAGE,
        ImageGenerationResult(
            prompt=prompt, model=model, image_bytes=image_bytes, mime_type=mime_type
        ),
    )
    saved_id = repository.save_record(ProjectId.IMAGE, record)

    # Retrieve and assert EXACT equality of the durable image bytes + MIME type.
    got = repository.get_record(ProjectId.IMAGE, saved_id)
    assert isinstance(got, ImageRecord)
    assert got.image_bytes == image_bytes  # byte-for-byte, incl. 0x00 and length
    assert got.mime_type == mime_type
    assert got.model == model

    # The history-detail re-emit path (encode then decode the durable bytes) returns
    # the original image bytes too, so a reopened record renders identically.
    payload = encode_image(got.image_bytes, got.mime_type)
    assert payload.mime_type in WEB_RENDERABLE_MIME_TYPES
    assert decode_image(payload) == image_bytes
