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
