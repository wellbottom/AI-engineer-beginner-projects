"""Property-based test for the Deep Research report structure (Property 16).

# Feature: ai-engineer-practice-monorepo, Property 16: the report has title, introduction, conclusion, and exactly one section per distinct sub-question

**Validates: Requirements 7.4**

For any set of researched sub-questions, :func:`app.logic.build_report_structure`
produces a :class:`ResearchReport` that has a (non-empty) title, a (non-empty)
introduction, a (non-empty) conclusion, and **exactly one section per distinct
sub-question**, where each section corresponds to one distinct sub-question (in
first-seen order). Duplicate and blank sub-questions are collapsed/removed so a
duplicate never yields two sections.

The generator injects duplicates and blank/whitespace-only entries to exercise the
de-duplication, and randomly supplies a subset of pre-built sections (body +
citations) to confirm they are matched to their sub-question by text and that every
distinct sub-question still gets exactly one section.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ai_shared.history import Citation, ReportSection
from app.logic import MAX_SUBQUESTIONS, MIN_SUBQUESTIONS, build_report_structure


def _distinct_in_order(raw: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        trimmed = item.strip()
        if trimmed and trimmed not in seen:
            seen.add(trimmed)
            out.append(trimmed)
    return out


# A pool of distinct sub-question cores; we sample WITH replacement to force dups.
_core = st.sampled_from([f"What about aspect {i}?" for i in range(1, 13)])
_blank = st.sampled_from(["", "   ", "\t", "\n "])

_subquestion_lists = st.lists(
    st.one_of(_core, _blank),
    min_size=MIN_SUBQUESTIONS,
    max_size=MAX_SUBQUESTIONS + 6,
)


# Feature: ai-engineer-practice-monorepo, Property 16: the report has title, introduction, conclusion, and exactly one section per distinct sub-question
@settings(max_examples=300, deadline=None)
@given(raw=_subquestion_lists, topic=st.text(min_size=1, max_size=30), data=st.data())
def test_report_has_one_section_per_distinct_subquestion(raw, topic, data) -> None:
    distinct = _distinct_in_order(raw)

    # Optionally supply pre-built sections for a random subset of the distinct SQs.
    chosen = data.draw(st.lists(st.sampled_from(distinct), max_size=len(distinct))) if distinct else []
    prebuilt = [
        ReportSection(
            sub_question=text,
            body=f"body for {text}",
            citations=[Citation(url=f"https://src/{i}", title=f"src {i}")],
        )
        for i, text in enumerate(dict.fromkeys(chosen))  # unique, preserve order
    ]

    report = build_report_structure(raw, topic=topic, sections=prebuilt)

    # Title, introduction, and conclusion are all present and non-empty.
    assert isinstance(report.title, str) and report.title.strip()
    assert isinstance(report.introduction, str) and report.introduction.strip()
    assert isinstance(report.conclusion, str) and report.conclusion.strip()

    # Exactly one section per DISTINCT sub-question, in first-seen order.
    assert [s.sub_question for s in report.sections] == distinct
    assert len(report.sections) == len(distinct)

    # No two sections share a sub-question (one section per distinct sub-question).
    section_texts = [s.sub_question for s in report.sections]
    assert len(section_texts) == len(set(section_texts))

    # A pre-built section's body/citations are carried onto the matching section.
    prebuilt_by_text = {s.sub_question: s for s in prebuilt}
    for section in report.sections:
        match = prebuilt_by_text.get(section.sub_question)
        if match is not None:
            assert section.body == match.body
            assert [c.url for c in section.citations] == [c.url for c in match.citations]
