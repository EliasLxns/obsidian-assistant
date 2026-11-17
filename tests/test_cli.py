import pytest

from assistant.cli import build_parser, main


@pytest.mark.parametrize(
    "argv",
    [["index", "demo_vault"], ["ask", "Welchen Port nutzt Ollama?"], ["eval"]],
)
def test_befehle_werden_erkannt(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    assert args.command == argv[0]


def test_stub_meldet_nicht_implementiert(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval"]) == 1
    assert "Phase 1" in capsys.readouterr().err
