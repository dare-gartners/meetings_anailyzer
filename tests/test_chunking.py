"""Tests for chunking.py — pure functions, no DB or LLM needed."""
from core.chunking import chunk_text


class TestTopicHeaderDetection:
    def test_basic_header_starts_chunk(self):
        chunks = chunk_text("Topic one:\n    content here")
        assert len(chunks) == 1
        assert "Topic one:" in chunks[0]

    def test_indented_line_ending_colon_is_not_header(self):
        notes = "Topic one:\n    sub-item:\n        nested content"
        chunks = chunk_text(notes)
        assert len(chunks) == 1

    def test_meeting_notes_label_not_header(self):
        notes = "Meeting notes:\nTopic one:\n    content"
        chunks = chunk_text(notes)
        assert len(chunks) == 1
        assert "Meeting notes" not in chunks[0]

    def test_meeting_notes_case_insensitive(self):
        notes = "MEETING NOTES:\nTopic one:\n    content"
        chunks = chunk_text(notes)
        assert len(chunks) == 1

    def test_preamble_before_first_header_is_skipped(self):
        notes = "preamble line\nanother preamble\nTopic one:\n    content"
        chunks = chunk_text(notes)
        assert len(chunks) == 1
        assert "preamble" not in chunks[0]

    def test_multiple_chunks(self):
        notes = "Topic one:\n    content a\nTopic two:\n    content b"
        chunks = chunk_text(notes)
        assert len(chunks) == 2
        assert "Topic one:" in chunks[0]
        assert "Topic two:" in chunks[1]

    def test_chunk_includes_all_indented_lines(self):
        notes = "Topic one:\n    line a\n    line b\n    line c"
        chunks = chunk_text(notes)
        assert "line a" in chunks[0]
        assert "line b" in chunks[0]
        assert "line c" in chunks[0]


class TestFollowUpTasksStripping:
    def test_follow_up_tasks_section_stripped(self):
        notes = "Topic one:\n    content\nfollow-up tasks:\n    action item"
        chunks = chunk_text(notes)
        assert "action item" not in "".join(chunks)

    def test_follow_up_tasks_case_insensitive_upper(self):
        notes = "Topic one:\n    content\nFOLLOW-UP TASKS:\n    action"
        chunks = chunk_text(notes)
        assert "action" not in "".join(chunks)

    def test_follow_up_tasks_case_insensitive_mixed(self):
        notes = "Topic one:\n    content\nFollow-Up Tasks:\n    action"
        chunks = chunk_text(notes)
        assert "action" not in "".join(chunks)

    def test_content_before_follow_up_preserved(self):
        notes = "Topic one:\n    keep this\nfollow-up tasks:\n    drop this"
        chunks = chunk_text(notes)
        assert "keep this" in "".join(chunks)


class TestFallback:
    def test_no_headers_returns_full_text_as_one_chunk(self):
        notes = "just plain text\nno headers here"
        chunks = chunk_text(notes)
        assert len(chunks) == 1
        assert "just plain text" in chunks[0]

    def test_empty_string_returns_one_chunk(self):
        chunks = chunk_text("")
        assert len(chunks) == 1

    def test_only_follow_up_tasks_returns_empty_or_single(self):
        notes = "follow-up tasks:\n    action"
        chunks = chunk_text(notes)
        # Everything stripped; fallback to empty-ish string
        assert isinstance(chunks, list)


class TestEdgeCases:
    def test_empty_chunk_between_consecutive_headers_not_added(self):
        notes = "Topic one:\nTopic two:\n    content"
        chunks = chunk_text(notes)
        assert all(c.strip() for c in chunks)

    def test_chunk_index_order(self):
        notes = "Alpha:\n    a\nBeta:\n    b\nGamma:\n    c"
        chunks = chunk_text(notes)
        assert len(chunks) == 3
        assert chunks[0].startswith("Alpha:")
        assert chunks[1].startswith("Beta:")
        assert chunks[2].startswith("Gamma:")

    def test_blank_lines_within_chunk_preserved(self):
        notes = "Topic one:\n    line a\n\n    line b"
        chunks = chunk_text(notes)
        assert "line a" in chunks[0]
        assert "line b" in chunks[0]
