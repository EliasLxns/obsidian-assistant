from pathlib import Path

import httpx
import pytest

from assistant.cli import Components, build_parser, main, start_watch
from assistant.config import Settings
from assistant.index.embedder import FakeEmbedder, OllamaEmbedder
from assistant.index.store import InMemoryStore
from assistant.llm.client import FakeLLM
from tests.conftest import DEMO_VAULT, QUESTIONS


class FakeApp:
    """Hält die Fake-Bausteine über mehrere CLI-Aufrufe hinweg, wie ein echter Index."""

    def __init__(self) -> None:
        self.llm = FakeLLM("Ollama nutzt Port 11434 [1].")
        self.components = Components(
            settings=Settings(vault_path=DEMO_VAULT, vault_name="demo_vault"),
            embedder=FakeEmbedder(),
            store=InMemoryStore(),
            llm=self.llm,
        )

    def __call__(self, settings: Settings) -> Components:
        return self.components


@pytest.mark.parametrize(
    "argv",
    [["index", "demo_vault"], ["ask", "Welchen Port nutzt Ollama?"], ["eval"]],
)
def test_befehle_werden_erkannt(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    assert args.command == argv[0]


def test_index_dann_ask(capsys: pytest.CaptureFixture[str]) -> None:
    app = FakeApp()
    assert main(["index", str(DEMO_VAULT)], app) == 0
    assert "25 Notizen" in capsys.readouterr().out

    assert main(["ask", "Welchen Port nutzt Ollama?"], app) == 0
    out = capsys.readouterr().out
    assert "Ollama nutzt Port 11434 [1]." in out
    assert "Quellen:" in out
    assert "obsidian://open?vault=demo_vault&file=03%20Wissen%2FHomelab%2FOllama" in out


def test_zweites_index_bettet_nichts_neu_ein(capsys: pytest.CaptureFixture[str]) -> None:
    app = FakeApp()
    main(["index", str(DEMO_VAULT)], app)
    main(["index", str(DEMO_VAULT)], app)
    assert ": 0 eingebettet" in capsys.readouterr().out.splitlines()[-1]


def test_ask_nur_suche_ohne_llm(capsys: pytest.CaptureFixture[str]) -> None:
    app = FakeApp()
    main(["index"], app)  # Pfad aus den Settings
    assert main(["ask", "--nur-suche", "Wann sind die Eisheiligen?"], app) == 0
    out = capsys.readouterr().out
    assert "[1] Aussaatkalender" in out
    assert app.llm.prompts == []


def test_ask_mit_leerem_index(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ask", "Hallo?"], FakeApp()) == 1
    assert "Index ist leer" in capsys.readouterr().err


def test_eval_zeigt_tabelle_und_speichert(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ziel = tmp_path / "ergebnis.md"
    argv = ["eval", "--vault", str(DEMO_VAULT), "--fragen", str(QUESTIONS), "--details"]
    assert main([*argv, "--ausgabe", str(ziel)], FakeApp()) == 0
    out = capsys.readouterr().out
    assert "| Typ | Fragen | Treffer@1 | Treffer@5 |" in out
    assert "| **gesamt** | 20 |" in out
    assert "Welchen Port nutzt Ollama?" in out
    assert ziel.read_text(encoding="utf-8").strip() == out.strip()


def test_ollama_nicht_erreichbar(capsys: pytest.CaptureFixture[str]) -> None:
    def kaputt(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    app = FakeApp()
    app.components.embedder = OllamaEmbedder(
        "http://192.168.1.50:11434",
        "bge-m3",
        client=httpx.Client(transport=httpx.MockTransport(kaputt)),
    )
    assert main(["index", str(DEMO_VAULT)], app) == 2
    assert "Gaming-PC wach" in capsys.readouterr().err


def test_vault_fehlt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["index", str(tmp_path / "gibtsnicht")], FakeApp()) == 1
    assert "Vault nicht gefunden" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["serve", "--port", "9000"], ["watch", "--warten", "0.5"]])
def test_serve_und_watch_werden_erkannt(argv: list[str]) -> None:
    assert build_parser().parse_args(argv).command == argv[0]


def test_watch_indexiert_beim_start_und_bei_aenderungen(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil
    import time

    vault = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, vault)
    app = FakeApp()
    observer, batcher = start_watch(app.components, vault, delay=0.1)
    try:
        assert "Start: 25 Notizen" in capsys.readouterr().out
        (vault / "00 Inbox/Neu.md").write_text("# Neu\n\nText.\n", encoding="utf-8")
        for _ in range(50):
            time.sleep(0.1)
            if "Änderung: 1 Notizen" in capsys.readouterr().out:
                break
        else:
            pytest.fail("Änderung wurde nicht nachindexiert")
    finally:
        observer.stop()
        observer.join(timeout=5)
        batcher.stop()
