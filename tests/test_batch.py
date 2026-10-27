"""Batch mode: one Message Batch per batchable stage, then the normal pass from cache."""

from research_kit.llm_backend import LLMError, Response

from research_kit import llm as L


def _llm(tmp_path, monkeypatch, outcome, sync_calls):
    batches = []

    def fake_run_batch(reqs, backend=None, **kw):
        batches.append([r.prompt for r in reqs])
        return [outcome(r.prompt) for r in reqs]

    def fake_ask(prompt, **kw):
        sync_calls.append(prompt)
        return Response(text='{"answer": "sync"}', backend="api", model="m")

    monkeypatch.setattr(L, "run_batch", fake_run_batch)
    monkeypatch.setattr(L, "ask", fake_ask)
    return L.LLM(tmp_path, batch=True, jobs=4), batches


def _stage(llm):
    return llm.pmap(lambda i: llm.json_call("extract", f"k{i}", f"prompt {i}")["answer"],
                    list(range(5)), "extract", batchable=True)


def test_one_batch_then_every_call_served_from_cache(tmp_path, monkeypatch):
    sync = []
    llm, batches = _llm(tmp_path, monkeypatch,
                        lambda p: Response(text=f'{{"answer": "{p}"}}', backend="api-batch", model="m"), sync)
    out = _stage(llm)
    assert out == [f"prompt {i}" for i in range(5)]
    assert len(batches) == 1 and len(batches[0]) == 5          # one batch for the stage
    assert sync == []                                            # nothing paid twice
    assert llm.usage_summary()["by_model"]["m"]["batch_calls"] == 5


def test_failures_fall_through_to_a_synchronous_call(tmp_path, monkeypatch):
    sync = []
    def outcome(p):
        if p == "prompt 2":
            return LLMError("batch item expired")
        if p == "prompt 3":
            return Response(text="not json", backend="api-batch", model="m")
        return Response(text='{"answer": "batched"}', backend="api-batch", model="m")
    llm, _ = _llm(tmp_path, monkeypatch, outcome, sync)
    out = _stage(llm)
    assert out == ["batched", "batched", "sync", "sync", "batched"]
    assert sorted(sync) == ["prompt 2", "prompt 3"]


def test_a_batch_refusal_is_asked_again_synchronously(tmp_path, monkeypatch):
    # Batches drop the server-side fallback; the synchronous call has it.
    sync = []
    llm, _ = _llm(tmp_path, monkeypatch, lambda p: LLMError("model refused: bio"), sync)
    out = _stage(llm)
    assert out == ["sync"] * 5 and len(sync) == 5
    assert not (tmp_path / "llm" / "extract" / "k0.refused.json").exists()


def test_web_search_calls_batch_and_keep_their_sources(tmp_path, monkeypatch):
    sync, seen = [], []
    def outcome(p):
        return Response(text='{"answer": "w"}', backend="api-batch+api", model="m",
                        sources=[{"url": "https://x", "title": "x"}], searches=["q"],
                        usage={"input_tokens": 100, "output_tokens": 10,
                               "batched": {"input_tokens": 60, "output_tokens": 6}})
    llm, _ = _llm(tmp_path, monkeypatch, outcome, sync)
    real = L.run_batch
    def spy(reqs, **kw):
        seen.extend(r.web_search.max_uses for r in reqs)
        return real(reqs, **kw)
    monkeypatch.setattr(L, "run_batch", spy)
    llm.pmap(lambda i: llm.json_call("profile", f"p{i}", f"q {i}", web_search=12), [0, 1],
             "profile", batchable=True)
    assert seen == [12, 12] and sync == []
    assert llm.sources("profile", "p0") == [{"url": "https://x", "title": "x"}]
    m = llm.usage_summary()["by_model"]["m"]
    assert (m["in"], m["batch_in"], m["batch_out"]) == (200, 120, 12)   # only the batched part at 50%


def test_batch_mode_is_off_by_default_and_non_batchable_stages_never_batch(tmp_path, monkeypatch):
    sync = []
    llm, batches = _llm(tmp_path, monkeypatch, lambda p: None, sync)
    llm.pmap(lambda i: llm.json_call("profile", f"p{i}", f"q {i}"), [0, 1], "profile")
    assert batches == [] and len(sync) == 2
    assert L.LLM(tmp_path).batch is False
