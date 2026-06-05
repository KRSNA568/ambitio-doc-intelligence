"""Tests for the learner's deterministic parts: diff computation and the
SQLite rule ledger (de-duplication, ordering). The Claude/Gemini rule-extraction
call itself is not unit-tested here since it requires the network."""

import importlib

import learner as learner_mod


def _fresh_learner(tmp_path, monkeypatch):
    """Re-import learner with the rules DB pointed at a temp file."""
    monkeypatch.setenv("RULES_DB_PATH", str(tmp_path / "rules.db"))
    importlib.reload(learner_mod)
    return learner_mod


def test_compute_diff_detects_changes():
    diff = learner_mod.compute_diff("hello world", "hello brave world")
    assert "ai_draft" in diff and "operator_edit" in diff
    assert "+hello brave world" in diff


def test_compute_diff_empty_when_identical():
    assert learner_mod.compute_diff("same text", "same text").strip() == ""


def test_store_and_get_rules(tmp_path, monkeypatch):
    mod = _fresh_learner(tmp_path, monkeypatch)
    mod._store_rules(["Use bullet points.", "Refer to parties by role."], "legal")
    rules = mod.get_rules()
    assert rules == ["Use bullet points.", "Refer to parties by role."]


def test_store_rules_deduplicates(tmp_path, monkeypatch):
    mod = _fresh_learner(tmp_path, monkeypatch)
    mod._store_rules(["Be concise."], "legal")
    total = mod._store_rules(["be concise.", "New rule."], "legal")  # case-insensitive dup
    rules = mod.get_rules()
    assert "Be concise." in rules
    assert "New rule." in rules
    assert len([r for r in rules if r.lower() == "be concise."]) == 1
    assert total == 2


def test_learn_from_edit_skips_when_no_change(tmp_path, monkeypatch):
    mod = _fresh_learner(tmp_path, monkeypatch)
    out = mod.learn_from_edit("identical", "identical")
    assert out["extracted_rules"] == []
    assert out["diff"] == ""
