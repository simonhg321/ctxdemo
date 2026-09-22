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
