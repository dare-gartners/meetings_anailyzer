"""Tests for llm_client.py — Azure OpenAI client is mocked throughout."""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch


def _chat_resp(content: str) -> MagicMock:
    r = MagicMock()
    r.choices[0].message.content = content
    return r


def _emb_resp(vec: list) -> MagicMock:
    r = MagicMock()
    r.data[0].embedding = vec
    return r


def _mock_client(chat_content: str = None, emb_vec: list = None):
    """Return a mock AzureOpenAI client."""
    m = MagicMock()
    if chat_content is not None:
        m.chat.completions.create.return_value = _chat_resp(chat_content)
    if emb_vec is not None:
        m.embeddings.create.return_value = _emb_resp(emb_vec)
    return m


class TestGenerateTags:
    def _call(self, llm_response: str, existing: list = None) -> list:
        from llm_client import generate_tags
        with patch("llm_client._client", return_value=_mock_client(chat_content=llm_response)):
            return generate_tags("some chunk text", existing or [])

    def test_returns_valid_tags(self):
        assert self._call('["roadmap", "budget", "hiring"]') == ["roadmap", "budget", "hiring"]

    def test_filters_tags_with_spaces(self):
        assert "in valid" not in self._call('["valid", "in valid"]')

    def test_filters_uppercase_tags(self):
        assert "UPPER" not in self._call('["UPPER", "lower"]')
        assert "lower" in self._call('["UPPER", "lower"]')

    def test_filters_underscore_tags(self):
        result = self._call('["ai_adoption", "ai-adoption"]')
        assert "ai_adoption" not in result
        assert "ai-adoption" in result

    def test_allows_hyphenated_tags(self):
        assert self._call('["ai-adoption"]') == ["ai-adoption"]

    def test_allows_alphanumeric_tags(self):
        assert self._call('["q3", "2024"]') == ["q3", "2024"]

    def test_strips_markdown_json_fence(self):
        assert self._call('```json\n["roadmap"]\n```') == ["roadmap"]

    def test_strips_plain_markdown_fence(self):
        assert self._call('```\n["hiring"]\n```') == ["hiring"]

    def test_with_existing_tags_does_not_crash(self):
        result = self._call('["budget"]', existing=["roadmap", "hiring"])
        assert isinstance(result, list)

    def test_empty_existing_tags_works(self):
        assert self._call('["budget"]', existing=[]) == ["budget"]

    def test_malformed_json_raises(self):
        from llm_client import generate_tags
        with patch("llm_client._client", return_value=_mock_client(chat_content="not json")):
            with pytest.raises(Exception):
                generate_tags("chunk", [])

    def test_non_string_items_filtered(self):
        result = self._call('["valid", 123, null]')
        assert result == ["valid"]


class TestVerifyMatch:
    def _call(self, response: str) -> bool:
        from llm_client import verify_match
        with patch("llm_client._client", return_value=_mock_client(chat_content=response)):
            return verify_match("desc a", "desc b")

    def test_yes_returns_true(self):
        assert self._call("yes") is True

    def test_yes_with_sentence_returns_true(self):
        assert self._call("Yes, they discuss the same topic.") is True

    def test_YES_returns_true(self):
        assert self._call("YES") is True

    def test_no_returns_false(self):
        assert self._call("no") is False

    def test_unrelated_answer_returns_false(self):
        assert self._call("not sure") is False

    def test_empty_returns_false(self):
        assert self._call("") is False


class TestGenerateDescription:
    def _call(self, response: str, chunk: str = "x" * 100) -> str:
        from llm_client import generate_description
        with patch("llm_client._client", return_value=_mock_client(chat_content=response)):
            return generate_description(chunk)

    def test_returns_description_when_shorter_than_chunk(self):
        chunk = "x" * 100
        assert self._call("short desc", chunk=chunk) == "short desc"

    def test_returns_original_chunk_when_description_longer(self):
        chunk = "short"
        result = self._call("this is much longer than the original chunk text", chunk=chunk)
        assert result == chunk

    def test_returns_original_chunk_when_same_length(self):
        # len(result) >= len(chunk) → return chunk
        chunk = "hello"
        assert self._call("hello", chunk=chunk) == chunk

    def test_strips_whitespace_from_response(self):
        chunk = "x" * 100
        assert self._call("  trimmed  ", chunk=chunk) == "trimmed"


class TestGenerateEmbedding:
    def test_returns_bytes(self):
        from llm_client import generate_embedding
        vec = [0.1, 0.2, 0.3, 0.4]
        with patch("llm_client._client", return_value=_mock_client(emb_vec=vec)):
            result = generate_embedding("hello")
        assert isinstance(result, bytes)

    def test_bytes_deserialize_to_float32(self):
        from llm_client import generate_embedding
        vec = [0.1, 0.2, 0.3]
        with patch("llm_client._client", return_value=_mock_client(emb_vec=vec)):
            result = generate_embedding("hello")
        recovered = np.frombuffer(result, dtype=np.float32)
        np.testing.assert_allclose(recovered, vec, rtol=1e-5)

    def test_vector_length_preserved(self):
        from llm_client import generate_embedding
        vec = list(range(1536))
        with patch("llm_client._client", return_value=_mock_client(emb_vec=vec)):
            result = generate_embedding("hello")
        assert len(np.frombuffer(result, dtype=np.float32)) == 1536


class TestExplainMatch:
    def test_returns_explanation_string(self):
        from llm_client import explain_match
        explanation = "Both meetings discussed budget planning."
        with patch("llm_client._client", return_value=_mock_client(chat_content=explanation)):
            result = explain_match("topic a", "topic b")
        assert result == explanation

    def test_strips_whitespace(self):
        from llm_client import explain_match
        with patch("llm_client._client", return_value=_mock_client(chat_content="  Both meetings discussed X.  ")):
            result = explain_match("a", "b")
        assert result == "Both meetings discussed X."
