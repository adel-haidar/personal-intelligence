"""Unit tests for the Brain Organiser core (pure-Python maths + workflow wiring).

No DB or Bedrock: data access and the merge helpers are monkeypatched so the
stage logic, union-find grouping and similarity thresholds are exercised
deterministically.
"""

import math

from private_internet.brain import organiser as org


def test_union_find_groups():
    uf = org._UnionFind(5)
    uf.union(0, 1)
    uf.union(1, 2)
    uf.union(3, 4)
    groups = sorted(sorted(g) for g in uf.groups().values())
    assert [0, 1, 2] in groups
    assert [3, 4] in groups


def test_cosine_normalized():
    a = org._normalize([1.0, 0.0])
    b = org._normalize([1.0, 0.0])
    c = org._normalize([0.0, 1.0])
    assert math.isclose(org._cosine(a, b), 1.0, rel_tol=1e-9)
    assert math.isclose(org._cosine(a, c), 0.0, abs_tol=1e-9)


def test_parse_vec():
    assert org._parse_vec("[1,2,3]") == [1.0, 2.0, 3.0]
    assert org._parse_vec(None) is None
    assert org._parse_vec("[]") is None


def test_union_tags_dedupes_and_unions():
    members = [{"tags": ["a", "b"]}, {"tags": ["b", "c"]}]
    assert org._union_tags(members, ["c", "d"]) == ["a", "b", "c", "d"]


def test_near_duplicates_merge_without_llm(monkeypatch):
    """Two near-identical memories (cosine 1.0) -> Stage-1 deterministic merge,
    no Bedrock call, sources soft-deleted, run logged."""
    mems = [
        {"id": "m1", "title": "Cat", "content": "I have a cat named Leo.", "tags": ["pets"], "vec": [1.0, 0.0, 0.0]},
        {"id": "m2", "title": "Cat", "content": "I have a cat named Leo. He is grey.", "tags": ["pets", "cat"], "vec": [1.0, 0.0, 0.0]},
        {"id": "m3", "title": "Car", "content": "I drive a Toyota.", "tags": ["cars"], "vec": [0.0, 1.0, 0.0]},
    ]
    monkeypatch.setattr(org, "_fetch_active", lambda uid: mems)
    monkeypatch.setattr(org, "_count_active", lambda uid: 2)  # after merge: m3 + merged
    monkeypatch.setattr(org, "_insert_run", lambda *a, **k: None)

    commits: list = []
    monkeypatch.setattr(org, "_commit_merge", lambda uid, members, content, tags: commits.append((members, content, tags)))

    def llm_should_not_be_called(_contents):
        raise AssertionError("Bedrock must not be called for near-duplicates")
    monkeypatch.setattr(org, "_llm_decide_merge", llm_should_not_be_called)

    captured = {}
    monkeypatch.setattr(org, "_complete_run", lambda run_id, **k: captured.update(k) or {"completed_at": "now", **k})

    org._RUNS["u1"] = {"status": "running", "run_id": "r1", "stage": 1, "stage_label": None,
                       "progress_pct": 0, "started_at": "now", "last_run": None, "error": None}
    org._run_organise("u1", "r1")

    assert len(commits) == 1                       # one near-dup group merged
    merged_members, merged_content, _ = commits[0]
    assert {m["id"] for m in merged_members} == {"m1", "m2"}
    assert merged_content == "I have a cat named Leo. He is grey."  # longest wins
    assert captured["dups"] == 2                    # both sources removed
    assert captured["clusters"] == 0               # no semantic merges
    assert org._RUNS["u1"]["status"] == "completed"


def test_semantic_band_uses_llm_and_respects_should_merge(monkeypatch):
    """Mid-similarity pair -> Bedrock decides. should_merge False => no commit."""
    import private_internet.brain.organiser as o
    a = o._normalize([1.0, 0.20, 0.0])
    b = o._normalize([1.0, 0.32, 0.0])  # cosine ~0.97? tune to land in band
    # Force them into the semantic band regardless of exact geometry:
    mems = [
        {"id": "m1", "title": "A", "content": "Trip to Rome in May.", "tags": ["travel"], "vec": a},
        {"id": "m2", "title": "B", "content": "Planning Italy holiday.", "tags": ["travel"], "vec": b},
    ]
    monkeypatch.setattr(o, "_fetch_active", lambda uid: mems)
    monkeypatch.setattr(o, "_count_active", lambda uid: 2)
    monkeypatch.setattr(o, "_insert_run", lambda *args, **k: None)
    monkeypatch.setattr(o, "NEAR_DUP_THRESHOLD", 0.999)   # push the pair into the LLM band
    monkeypatch.setattr(o, "SEMANTIC_LOW", 0.5)

    monkeypatch.setattr(o, "_llm_decide_merge", lambda contents: {"should_merge": False, "merged_content": "", "tags": [], "reason": "different"})
    commits: list = []
    monkeypatch.setattr(o, "_commit_merge", lambda *a, **k: commits.append(a))
    captured = {}
    monkeypatch.setattr(o, "_complete_run", lambda run_id, **k: captured.update(k) or {"completed_at": "now", **k})

    o._RUNS["u2"] = {"status": "running", "run_id": "r2", "stage": 1, "stage_label": None,
                     "progress_pct": 0, "started_at": "now", "last_run": None, "error": None}
    o._run_organise("u2", "r2")

    assert commits == []                 # should_merge False -> nothing committed
    assert captured["clusters"] == 0
