from __future__ import annotations

import httpx
import pytest
from pais.contracts import Chunk, SearchHit
from pais.models import (
    LocalModels,
    MissingPrerequisite,
    ModelFailure,
    get_models,
    sentences_with_spans,
)


def test_fixture_is_explicit_and_missing_local_models_do_not_fallback(monkeypatch):
    monkeypatch.delenv("PAIS_MODEL_LOCK", raising=False)
    assert get_models("fixture").metadata()["real_inference"] is False
    with pytest.raises(MissingPrerequisite, match="lock missing"):
        get_models("local")
    with pytest.raises(MissingPrerequisite, match="not configured"):
        get_models("connected")


def test_sentence_spans_preserve_decimal_negation_and_newline():
    text = "Access is not\nallowed. The timeout is 3.5 seconds.\n"
    spans = sentences_with_spans(text)
    assert [quote for _, _, quote in spans] == ["Access is not\nallowed.", "The timeout is 3.5 seconds."]
    assert all(text[start:end] == quote for start, end, quote in spans)


def test_ollama_embedding_http_contract_and_invalid_dimension_fail_closed():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "embed:test", "digest": "a" * 64},
                {"name": "generate:test", "digest": "b" * 64},
            ]})
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
    model = LocalModels.__new__(LocalModels)
    model.client = httpx.Client(base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(handler))
    model.lock = {"embedding": {"name": "embed:test", "digest": "a" * 64},
                  "generation": {"name": "generate:test", "digest": "b" * 64}}
    model.url = "http://127.0.0.1:11434"
    model.dimension = 384
    model.threads = 2
    with pytest.raises(ModelFailure, match="dimension mismatch"):
        model.embed(["hello"])
    import json
    body = json.loads(requests[-1].content)
    assert requests[-1].url.path == "/api/embed"
    assert body["input"] == ["hello"]
    assert body["truncate"] is False
    assert body["keep_alive"] == "0"


def test_ollama_model_digest_drift_fails_before_inference():
    model = LocalModels.__new__(LocalModels)
    model.url = "http://127.0.0.1:11434"
    model.client = httpx.Client(base_url=model.url, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"models": [{"name": "x", "digest": "b" * 64}]})))
    model.lock = {"embedding": {"name": "x", "digest": "a" * 64},
                  "generation": {"name": "x", "digest": "a" * 64}}
    with pytest.raises(MissingPrerequisite, match="digest changed"):
        model._verify_ollama()


@pytest.mark.parametrize("selection,expected_error", [
    (["s1", "s2"], False), (["s999"], True), (["s1", "s1"], True),
])
def test_local_generation_binds_short_ids_to_individual_verbatim_sentences(selection, expected_error):
    import json

    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "x", "digest": "a" * 64}]})
        return httpx.Response(200, json={"done": True, "done_reason": "stop", "response": json.dumps({
            "sentence_ids": selection, "abstain": False,
        })})
    model = LocalModels.__new__(LocalModels)
    model.url = "http://127.0.0.1:11434"
    model.client = httpx.Client(base_url=model.url, transport=httpx.MockTransport(handler))
    model.lock = {role: {"name": "x", "digest": "a" * 64} for role in ("embedding", "generation")}
    model.generator_id = "http-contract-test-only"
    model.threads = 2
    text = "Retention is 30 days. Access requires approval."
    hit = SearchHit(chunk=Chunk(chunk_id="c" * 64, document_id="doc", version_id="v1",
                               tenant_id="test", page_number=1, start=0, end=len(text), text=text), score=1)
    if expected_error:
        with pytest.raises(ModelFailure, match="unknown or duplicate"):
            model.generate("What are the retention and access requirements?", [hit])
    else:
        output = model.generate("What are the retention and access requirements?", [hit])
        assert [claim.quote for claim in output.claims.claims] == [
            "Retention is 30 days.", "Access requires approval."]
        assert all(claim.quote == claim.claim for claim in output.claims.claims)
        assert json.loads(output.evidence["raw_model_output"])["sentence_ids"] == selection
    body = json.loads(requests[-1].content)
    assert "c" * 64 not in body["prompt"]
    assert body["format"]["properties"]["sentence_ids"]["items"]["enum"] == ["s1", "s2"]
