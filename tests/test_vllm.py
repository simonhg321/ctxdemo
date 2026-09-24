import json, httpx
from app.vllm import VLLM, ChatResult, parse_logprobs


def test_fake_counts_words(fake):
    assert fake.count("one two three") == 3
    assert fake.count_messages([{"role": "user", "content": "a b"}]) == 6


def test_chat_body_and_result():
    seen = {}
    def handler(req: httpx.Request):
        seen["json"] = json.loads(req.content); seen["path"] = req.url.path
        return httpx.Response(200, json={"choices": [{"message": {"content": " hi "}}],
                                         "usage": {"prompt_tokens": 12, "completion_tokens": 1}})
    v = VLLM("http://x", "m", transport=httpx.MockTransport(handler))
    r = v.chat([{"role": "user", "content": "hello"}], max_tokens=5)
    assert isinstance(r, ChatResult) and r.text == "hi" and r.prompt_tokens == 12 and r.completion_tokens == 1
    assert seen["path"] == "/v1/chat/completions"
    assert seen["json"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["json"]["temperature"] == 0 and seen["json"]["max_tokens"] == 5


def test_count_uses_tokenize():
    def handler(req):
        j = json.loads(req.content)
        return httpx.Response(200, json={"count": 7 if "prompt" in j else 9})
    v = VLLM("http://x", "m", transport=httpx.MockTransport(handler))
    assert v.count("x") == 7
    assert v.count_messages([{"role": "user", "content": "x"}]) == 9


def test_count_falls_back_to_estimate_without_tokenize():
    def handler(req):
        if req.url.path == "/tokenize": return httpx.Response(404)
        return httpx.Response(200, json={"data": []})
    v = VLLM("http://x", "m", transport=httpx.MockTransport(handler))
    assert v.count("hello there world, this is text") > 0 and v.exact is False
    assert v.count_messages([{"role": "user", "content": "hello"}]) >= 5
    assert v.health() is True   # /v1/models answers even though /health is not 200


def test_chat_returns_tool_calls_and_look_sends_image():
    seen = []
    def handler(req):
        j = json.loads(req.content); seen.append(j)
        if "tools" in j:
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query":"x"}'}}]}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "READ ME"}}], "usage": {"prompt_tokens": 1500, "completion_tokens": 3}})
    v = VLLM("http://x", "m", transport=httpx.MockTransport(handler))
    r = v.chat([{"role": "user", "content": "hi"}], 5, tools=[{"type": "function", "function": {"name": "web_search"}}])
    assert r.text == "" and r.tool_calls[0]["function"]["name"] == "web_search"
    r2 = v.look("QUJD", "read it")
    assert r2.text == "READ ME" and r2.prompt_tokens == 1500
    parts = seen[1]["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "read it"} and parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,QUJD")


OLLAMA_CHOICE = {"message": {"content": "Hi there"}, "logprobs": {"content": [
    {"token": "Hi", "logprob": -0.32893359661102295, "bytes": [72, 105], "top_logprobs": [
        {"token": "Hi", "logprob": -0.32893359661102295, "bytes": [72, 105]},
        {"token": "Hello", "logprob": -1.271865725517273, "bytes": [72, 101, 108, 108, 111]}]},
    {"token": " there", "logprob": -4.768372718899627e-07, "bytes": [32, 116, 104, 101, 114, 101], "top_logprobs": [
        {"token": " there", "logprob": -4.768372718899627e-07, "bytes": [32, 116, 104, 101, 114, 101]},
        {"token": " هناك", "logprob": -15.563672065734863, "bytes": [32, 217, 135, 217, 134, 216, 167, 217, 131]}]}]}}


def test_parse_logprobs_real_ollama_shape():
    toks = parse_logprobs(OLLAMA_CHOICE)
    assert [t["t"] for t in toks] == ["Hi", " there"]
    assert toks[0]["p"] == 0.7197 and toks[0]["alts"] == [{"t": "Hi", "p": 0.7197}, {"t": "Hello", "p": 0.2803}]
    assert toks[1]["p"] == 1.0 and toks[1]["alts"][1]["t"] == " هناك"


def test_parse_logprobs_is_tolerant():
    assert parse_logprobs({}) == [] and parse_logprobs({"logprobs": None}) == [] and parse_logprobs(None) == []
    assert parse_logprobs({"logprobs": {"content": "garbage"}}) == []
    # half a UTF-8 character must not crash; no bytes -> falls back to the token string
    half = {"logprobs": {"content": [{"token": "x", "logprob": -0.1, "bytes": [240, 159], "top_logprobs": []},
                                     {"token": "plain", "logprob": -0.2}]}}
    toks = parse_logprobs(half)
    assert toks[0]["t"] == "�" and toks[1]["t"] == "plain"
    # the chosen piece is always in alts, even if the server left it out
    assert toks[0]["alts"] == [{"t": "�", "p": 0.9048}]


def test_peek_adds_fields_and_default_body_is_unchanged():
    bodies = []
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        bodies.append(body)
        choice = OLLAMA_CHOICE if body.get("logprobs") else {"message": {"content": "Hi there"}}
        return httpx.Response(200, json={"choices": [choice], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
    v = VLLM("http://x", "m", transport=httpx.MockTransport(handler))
    plain = v.chat([{"role": "user", "content": "hello"}], max_tokens=5)
    peeked = v.chat([{"role": "user", "content": "hello"}], max_tokens=5, peek=True)
    assert bodies[0] == {"model": "m", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 5,
                         "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
    assert bodies[1]["logprobs"] is True and bodies[1]["top_logprobs"] == 5
    assert plain.tokens == [] and [t["t"] for t in peeked.tokens] == ["Hi", " there"]


def test_parse_logprobs_drops_end_of_turn_marker():
    choice = {"logprobs": {"content": [
        {"token": "Hi", "logprob": -0.1, "top_logprobs": [{"token": "Hi", "logprob": -0.1}]},
        {"token": "<|im_end|>", "logprob": -0.01, "top_logprobs": [{"token": "<|im_end|>", "logprob": -0.01}]}]}}
    assert [t["t"] for t in parse_logprobs(choice)] == ["Hi"]        # vLLM lists the stop token as a piece; Ollama does not


def test_chat_sets_cut_on_finish_reason_length():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "abc"}, "finish_reason": "length"}], "usage": {}})
    v = VLLM("http://x", "m", transport=httpx.MockTransport(handler))
    assert v.chat([{"role": "user", "content": "hi"}], 5).cut is True


def test_count_messages_empty_never_calls_server():
    def handler(request):
        raise AssertionError("should not be called")
    v = VLLM("http://x", "m", transport=httpx.MockTransport(handler))
    assert v.count_messages([]) == 0


def test_chat_keeps_the_wire():
    """The wire panel shows the exact bytes: the body we posted and the JSON that came back."""
    raw = {"choices": [{"message": {"content": "hi"}, "logprobs": {"content": [{"token": "hi", "logprob": 0.0, "top_logprobs": []}]}}],
           "usage": {"prompt_tokens": 12, "completion_tokens": 1}}
    v = VLLM("http://x", "m", transport=httpx.MockTransport(lambda req: httpx.Response(200, json=raw)))
    r = v.chat([{"role": "user", "content": "hello"}], max_tokens=5, peek=True)
    assert r.wire["request"]["messages"] == [{"role": "user", "content": "hello"}]
    assert r.wire["request"]["logprobs"] is True and r.wire["request"]["top_logprobs"] == 5
    assert r.wire["response"] == raw


def test_trim_wire_keeps_the_first_pieces_and_says_how_many_there_were():
    from app.vllm import trim_wire
    content = [{"token": str(i), "logprob": -0.1, "top_logprobs": []} for i in range(100)]
    wire = {"request": {"a": 1}, "response": {"choices": [{"message": {"content": "x"}, "logprobs": {"content": content}}]}}
    t = trim_wire(wire, keep=40)
    assert len(t["response"]["choices"][0]["logprobs"]["content"]) == 40
    assert t["response"]["choices"][0]["logprobs"]["content"][39]["token"] == "39"
    assert t["shown"] == 40 and t["total"] == 100 and t["request"] == {"a": 1}
    assert len(content) == 100                                   # the original is untouched
    assert trim_wire(None) is None
    assert trim_wire({"request": {}, "response": {"choices": []}})["total"] == 0


def test_queue_parses_vllm_metrics_and_is_none_without_them():
    metrics = ('# HELP vllm:num_requests_running x\nvllm:num_requests_running{engine="0",model_name="m"} 3.0\n'
               'vllm:num_requests_waiting{engine="0",model_name="m"} 2.0\nvllm:kv_cache_usage_perc{engine="0",model_name="m"} 0.42\n')
    v = VLLM("http://x", "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, text=metrics)))
    assert v.queue() == {"running": 3, "waiting": 2, "kv_pct": 42}
    v2 = VLLM("http://x", "m", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert v2.queue() is None


def test_wait_for_model_polls_until_the_server_serves_it():
    state = {"n": 0}
    def handler(req):
        state["n"] += 1
        if req.url.path == "/health": return httpx.Response(200)
        return httpx.Response(200, json={"data": [{"id": "new" if state["n"] > 4 else "old"}]})
    v = VLLM("http://x", "old", transport=httpx.MockTransport(handler))
    assert v.wait_for_model("new", timeout=5, every=0.01) is True and v.model == "new"
    assert v.wait_for_model("never", timeout=0.05, every=0.01) is False


def test_refresh_model_keeps_the_configured_one_when_the_server_lists_many():
    """Ollama lists every model it has; keep ours. vLLM lists exactly one; take it (the model switch renames it)."""
    many = lambda r: httpx.Response(200, json={"data": [{"id": "other"}, {"id": "mine"}]})
    v = VLLM("http://x", "mine", transport=httpx.MockTransport(many)); assert v.refresh_model() == "mine"
    one = lambda r: httpx.Response(200, json={"data": [{"id": "served"}]})
    v2 = VLLM("http://x", "configured", transport=httpx.MockTransport(one)); assert v2.refresh_model() == "served"


def test_clamp_sampling_bounds_the_dials_and_drops_defaults():
    from app.vllm import clamp_sampling
    assert clamp_sampling(None) is None and clamp_sampling({}) is None and clamp_sampling({"temperature": 0}) is None
    assert clamp_sampling({"temperature": 9, "top_p": 2, "top_k": 0, "repetition_penalty": 0}) == {"temperature": 2.0, "repetition_penalty": 0.5}
    assert clamp_sampling({"temperature": "0.6", "top_k": 40.7, "junk": 1}) == {"temperature": 0.6, "top_k": 40}
    assert clamp_sampling({"top_p": 0.0}) == {"top_p": 0.01}
    assert clamp_sampling({"temperature": "abc"}) is None
