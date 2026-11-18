import importlib.util
import os
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest


spec = importlib.util.spec_from_file_location("secret_install",
    Path(__file__).resolve().parents[1] / "scripts/install_cloudflare_origin_secret.py")
assert spec is not None and spec.loader is not None
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
SECRET = "a" * 64


def test_token_uses_stdin_never_arguments_or_environment(capsys):
    with patch.object(Path, "is_file", return_value=True), patch.object(script.subprocess, "run") as run:
        run.return_value = CompletedProcess([], 0, "hidden", "")
        script.install(SECRET)
    args, kwargs = run.call_args
    assert SECRET not in str(args)
    assert SECRET not in str(kwargs["env"])
    assert kwargs["input"] == SECRET + "\n"
    assert kwargs["capture_output"] is True
    assert kwargs["env"]["WRANGLER_LOG_PATH"] == os.devnull
    assert "phineas-finance" in args[0]
    assert "ORIGIN_TOKEN" in args[0]
    assert capsys.readouterr().out == ""


def test_cli_failure_never_echoes_token_or_output(capsys):
    with patch.object(Path, "is_file", return_value=True), patch.object(script.subprocess, "run") as run:
        run.return_value = CompletedProcess([], 1, SECRET, SECRET)
        with pytest.raises(ValueError, match="transfer_unconfirmed"):
            script.install(SECRET)
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


@pytest.mark.parametrize("value", ["", "short", "a" * 65, "é" * 64])
def test_malformed_token_never_reaches_cli(value):
    with patch.object(script.subprocess, "run") as run:
        with pytest.raises(ValueError):
            script.install(value)
    run.assert_not_called()
