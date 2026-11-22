import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_are_development(monkeypatch):
    monkeypatch.delenv("AGENTGUARD_ENV", raising=False)
    s = Settings(_env_file=None)
    assert s.env == "development"
    assert s.docs_enabled is True


def test_reads_prefixed_env_vars(monkeypatch):
    monkeypatch.setenv("AGENTGUARD_ENV", "production")
    monkeypatch.setenv("AGENTGUARD_OPA_URL", "http://opa:8181")
    s = Settings(_env_file=None)
    assert s.env == "production"
    assert s.opa_url == "http://opa:8181"
    assert s.docs_enabled is False


def test_rejects_unknown_env(monkeypatch):
    monkeypatch.setenv("AGENTGUARD_ENV", "staging-ish")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
