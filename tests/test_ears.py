import base64, httpx
from app.ears import Ears, split_wake


def test_split_wake_fuzzy_and_remainder():
    assert split_wake("High Compaq demo, what is the tallest mountain in Washington?") == (True, "what is the tallest mountain in washington")
    assert split_wake("hi compact demo") == (True, "")
    assert split_wake("Hey, Compact Demo. What's the weather?") == (True, "what's the weather")
    assert split_wake("what is the weather in spokane") == (False, "")
    assert split_wake("the demo is compact") == (False, "")
    assert split_wake("check Hi-Compact demo") == (True, "")                 # whisper hallucinates a lead word
    assert split_wake("um so hi compact demo what is 2 times 2") == (True, "what is 2 times 2")


def test_transcribe_posts_multipart():
    seen = {}
    def handler(req: httpx.Request):
        seen["path"] = req.url.path; seen["ct"] = req.headers["content-type"]; seen["body"] = req.content
        return httpx.Response(200, json={"text": " hello there\n"})
    e = Ears("http://w", transport=httpx.MockTransport(handler))
    r = e.transcribe(base64.b64encode(b"OPUSDATA").decode(), "audio/webm;codecs=opus")
    assert r.text == "hello there" and seen["path"] == "/inference"
    assert seen["ct"].startswith("multipart/form-data") and b"OPUSDATA" in seen["body"] and b'filename="clip.webm"' in seen["body"]


def test_spoken_commands():
    from app.ears import spoken_command
    assert spoken_command("Compact.") == "COMPACT"
    assert spoken_command("hand off") == "HANDOFF" and spoken_command("Handoff!") == "HANDOFF"
    assert spoken_command("start over") == "RESET" and spoken_command("reset") == "RESET"
    assert spoken_command("compact the conversation please") is None      # a sentence is a question, not a command
    assert spoken_command("") is None
