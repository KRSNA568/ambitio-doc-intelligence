"""Tests for the lenient JSON extractor — the part that makes Gemini output
(fences + trailing prose) safe to parse."""

import pytest

import llm


def test_plain_object():
    assert llm.extract_json('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_fenced_json():
    text = "```json\n{\"ok\": true}\n```"
    assert llm.extract_json(text) == {"ok": True}


def test_trailing_prose_is_ignored():
    # raw_decode must stop after the first complete value.
    text = '{"x": 10}\n\nThis JSON describes the value of x.'
    assert llm.extract_json(text) == {"x": 10}


def test_leading_prose_before_object():
    text = 'Here is your answer:\n{"y": 5}'
    assert llm.extract_json(text) == {"y": 5}


def test_array_payload():
    text = '```\n["rule one", "rule two"]\n```'
    assert llm.extract_json(text) == ["rule one", "rule two"]


def test_no_json_raises():
    with pytest.raises(ValueError):
        llm.extract_json("there is no json here at all")
