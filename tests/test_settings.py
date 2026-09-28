"""Settings parsing, env aliases, and the .env writer."""

from __future__ import annotations

from kubemedic import settings as settings_module
from kubemedic.settings import Backend, Settings, write_env_values


def test_blank_credentials_become_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    s = Settings()
    assert s.openai_api_key is None


def test_env_aliases_map_to_fields(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("AUTO_FIX", "true")
    s = Settings()
    assert s.backend is Backend.OPENAI
    assert s.auto_approve is True


def test_active_model_tracks_backend(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5")
    assert Settings().active_model == "qwen2.5"


def test_resolve_kubeconfig_prefers_explicit(monkeypatch, tmp_path):
    cfg = tmp_path / "kubeconfig"
    cfg.write_text("apiVersion: v1", encoding="utf-8")
    monkeypatch.setenv("KUBECONFIG_PATH_UNUSED", "x")
    s = Settings(kubeconfig=str(cfg))
    assert s.resolve_kubeconfig() == str(cfg)


def test_write_env_values_updates_in_place(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nLLM_PROVIDER=ollama\nOLLAMA_MODEL=llama3.2\n", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_PATH", env)

    write_env_values({"LLM_PROVIDER": "openai", "OPENAI_MODEL": "gpt-4o"})

    result = env.read_text(encoding="utf-8")
    assert "LLM_PROVIDER=openai" in result
    assert "OLLAMA_MODEL=llama3.2" in result  # untouched
    assert "OPENAI_MODEL=gpt-4o" in result     # appended
    assert result.startswith("# comment")       # comments preserved


def test_write_env_values_bootstraps_from_example(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    (tmp_path / ".env.example").write_text("LLM_PROVIDER=ollama\n", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_PATH", env)

    write_env_values({"OPENAI_API_KEY": "sk-test"})

    assert env.exists()
    assert "OPENAI_API_KEY=sk-test" in env.read_text(encoding="utf-8")
