"""Lab logins: `name:password` checked against a Caddy-style htpasswd (`name bcrypt-hash` per line)."""
import bcrypt
from app.labauth import LabAuth


def line(name, pw):
    return f"{name} {bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()}\n"


def test_good_login_returns_the_name(tmp_path):
    f = tmp_path / "htpasswd"; f.write_text(line("simon", "hunter2") + line("ada", "x:y"))
    la = LabAuth(f)
    assert la.verify("simon:hunter2") == "simon"
    assert la.verify("ada:x:y") == "ada"                         # only the first colon splits: passwords may hold colons


def test_wrong_password_unknown_user_and_no_colon_are_refused(tmp_path):
    f = tmp_path / "htpasswd"; f.write_text(line("simon", "hunter2"))
    la = LabAuth(f)
    assert la.verify("simon:wrong") is None
    assert la.verify("nobody:hunter2") is None
    assert la.verify("hunter2") is None and la.verify("simon") is None
    assert la.verify(":hunter2") is None and la.verify("simon:") is None and la.verify("") is None


def test_name_match_is_exact_not_a_prefix(tmp_path):
    f = tmp_path / "htpasswd"; f.write_text(line("bobby", "pw-bobby") + line("bob", "pw-bob"))
    la = LabAuth(f)
    assert la.verify("bob:pw-bob") == "bob" and la.verify("bobby:pw-bobby") == "bobby"
    assert la.verify("bob:pw-bobby") is None and la.verify("bobby:pw-bob") is None and la.verify("bo:pw-bob") is None


def test_missing_file_bad_hash_and_duplicates_are_refused(tmp_path):
    assert LabAuth(tmp_path / "nope").verify("simon:hunter2") is None
    assert LabAuth(None).verify("simon:hunter2") is None
    f = tmp_path / "htpasswd"; f.write_text("simon notahash\n")
    assert LabAuth(f).verify("simon:hunter2") is None
    f.write_text(line("simon", "hunter2") + line("simon", "hunter2"))
    assert LabAuth(f).verify("simon:hunter2") is None              # listed twice: ambiguous, refused


def test_file_is_reread_on_every_call(tmp_path):
    f = tmp_path / "htpasswd"; f.write_text(line("simon", "hunter2"))
    la = LabAuth(f)
    assert la.verify("simon:hunter2") == "simon"
    f.write_text(line("simon", "new-pw"))                          # a password reset
    assert la.verify("simon:hunter2") is None and la.verify("simon:new-pw") == "simon"
    f.write_text("")                                               # the user is removed
    assert la.verify("simon:new-pw") is None
