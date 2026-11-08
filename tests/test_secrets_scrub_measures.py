"""Live 2026-11-08: "'token': 11.24" (seconds to the first token of a guest chat answer) was redacted, and the kernel
then held the number as seen in no output. A decimal fraction under a key that is secret only by "token" is a measure;
every credential shape stays redacted."""
from imperal_mcp.secrets_scrub import scrub_secrets


def test_a_timing_under_token_stays():
    s = "first at s: {'status': 2.87, 'token': 10.33, 'done': 14.49}"
    assert scrub_secrets(s) == s


def test_credentials_stay_redacted():
    for s in ("token=482913", "token: abcdEF123456", "password=1.5", "GITHUB_TOKEN=ghp_abcdefghijklmnopqrst",
              "auth_token: 'x.y'", "secret_token=12.5"):
        assert "[REDACTED]" in scrub_secrets(s), s
