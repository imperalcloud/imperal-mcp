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


def test_panel_url_default_and_override(monkeypatch):
    monkeypatch.delenv("IMPERAL_PANEL_URL", raising=False)
    assert Config.from_env().panel_url == "https://panel.imperal.io"
    monkeypatch.setenv("IMPERAL_PANEL_URL", "http://localhost:3000")
    assert Config.from_env().panel_url == "http://localhost:3000"


def test_panel_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("IMPERAL_PANEL_URL", "http://localhost:3000/")
    assert Config.from_env().panel_url == "http://localhost:3000"
