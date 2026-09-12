import json, httpx
from app.vllm import VLLM, ChatResult


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
