from pathlib import Path

from assistant.config import load_settings


def test_env_datei_und_umgebung(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# Kommentar\nOLLAMA_URL=http://192.168.1.50:11434/\nEMBED_MODEL='nomic-embed-text'\n"
        "VAULT_NAME=Brain\n",
        encoding="utf-8",
    )
    s = load_settings(env, environ={"VAULT_NAME": "Anders"})
    assert s.ollama_url == "http://192.168.1.50:11434"
    assert s.embed_model == "nomic-embed-text"
    assert s.vault_name == "Anders"  # Umgebung schlägt .env
    assert s.chat_model  # Standardwert bleibt


def test_ohne_env_datei(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "fehlt", environ={})
    assert s.vault_path == Path("demo_vault")
