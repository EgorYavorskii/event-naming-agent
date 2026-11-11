import pytest

from src.openrouter_client import OpenRouterError, _extract_json


def test_extract_json_from_string():
    assert _extract_json('{"status":"ok"}') == {"status": "ok"}


def test_extract_json_from_content_parts():
    content = [{"type": "text", "text": '{"status":"ok","questions":[]}'}]
    assert _extract_json(content) == {"status": "ok", "questions": []}


def test_extract_json_from_dict():
    assert _extract_json({"status": "ok"}) == {"status": "ok"}


def test_empty_content_has_clear_error():
    with pytest.raises(OpenRouterError, match="пустой ответ"):
        _extract_json(None)
