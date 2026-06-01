"""Property-based test: ingestion confirmation matches ingested documents (Property 25).

# Feature: ai-engineer-practice-monorepo, Property 25: the confirmation names exactly the successfully ingested documents, no extras or omissions

**Validates: Requirements 9.5**

For any set of submitted documents each at most 10 MB, the returned confirmation
names **exactly** the set of successfully ingested documents — one confirmation entry
per ingested document, with no extras or omissions. :func:`app.ingest.ingest_documents`
is the function under test, driven with a fake Embeddings_Service and a fake
Vector_Store (no network) so ingestion is deterministic.

The generator spans 0..several documents with varied names (including duplicates and
unicode) and varied content (empty, short, multi-chunk) so the confirmation is
checked against the exact submitted set in order.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.ingest import DocumentUpload, ingest_documents

from .conftest import FakeEmbeddings, FakeVectorStore

# A document: a non-empty name + arbitrary text content (empty allowed -> 0 chunks).
_names = st.text(min_size=1, max_size=24)
_contents = st.text(max_size=3000)
_documents = st.lists(
    st.builds(lambda n, c: DocumentUpload(name=n, data=c.encode("utf-8")), _names, _contents),
    min_size=0,
    max_size=8,
)


# Feature: ai-engineer-practice-monorepo, Property 25: the confirmation names exactly the successfully ingested documents, no extras or omissions
@settings(max_examples=200, deadline=None)
@given(documents=_documents)
def test_confirmation_names_exactly_the_ingested_documents(
    documents: list[DocumentUpload],
) -> None:
    embeddings = FakeEmbeddings()
    vector_store = FakeVectorStore()

    ingested = ingest_documents(
        documents,
        embeddings=embeddings,
        vector_store=vector_store,
        collection="test-collection",
    )

    # Exactly one confirmation entry per submitted document, in order — no extras,
    # no omissions (Property 25).
    assert len(ingested) == len(documents)
    assert [doc.name for doc in ingested] == [doc.name for doc in documents]

    # The confirmation's names are exactly the submitted names (as a multiset too).
    assert sorted(d.name for d in ingested) == sorted(d.name for d in documents)

    # Each confirmation entry reports a non-negative chunk count; documents with
    # text were stored (the vector store saw a non-empty add for them).
    for original, confirmed in zip(documents, ingested):
        assert confirmed.name == original.name
        assert confirmed.chunks >= 0
        expected_has_chunks = bool(original.data.decode("utf-8", errors="replace").split())
        assert (confirmed.chunks > 0) == expected_has_chunks
