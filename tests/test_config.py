from imperal_mcp.config import Config
from imperal_mcp import __version__


def test_version_present():
    assert isinstance(__version__, str) and __version__

def test_from_env_defaults(monkeypatch):
    monkeypatch.delenv("IMPERAL_API_URL", raising=False)
    monkeypatch.delenv("IMPERAL_TOKEN", raising=False)
    c = Config.from_env()
    assert c.api_url == "https://auth.imperal.io"
    assert c.token is None

def test_from_env_overrides(monkeypatch):
    monkeypatch.setenv("IMPERAL_API_URL", "http://127.0.0.1:8085")
    monkeypatch.setenv("IMPERAL_TOKEN", "jwt-abc")
    c = Config.from_env()
    assert c.api_url == "http://127.0.0.1:8085"
    assert c.token == "jwt-abc"
