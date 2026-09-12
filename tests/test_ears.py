import base64, httpx
from app.ears import Ears, split_wake


def test_split_wake_fuzzy_and_remainder():
    assert split_wake("High Compaq demo, what is the tallest mountain in Washington?") == (True, "what is the tallest mountain in washington")
    assert split_wake("hi compact demo") == (True, "")
    assert split_wake("Hey, Compact Demo. What's the weather?") == (True, "what's the weather")
    assert split_wake("what is the weather in spokane") == (False, "")
    assert split_wake("the demo is compact") == (False, "")


def test_transcribe_posts_multipart():
    seen = {}
    def handler(req: httpx.Request):
        seen["path"] = req.url.path; seen["ct"] = req.headers["content-type"]; seen["body"] = req.content
        return httpx.Response(200, json={"text": " hello there\n"})
    e = Ears("http://w", transport=httpx.MockTransport(handler))
    r = e.transcribe(base64.b64encode(b"OPUSDATA").decode(), "audio/webm;codecs=opus")
    assert r.text == "hello there" and seen["path"] == "/inference"
    assert seen["ct"].startswith("multipart/form-data") and b"OPUSDATA" in seen["body"] and b'filename="clip.webm"' in seen["body"]
