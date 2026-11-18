import importlib.util
import os
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest


spec = importlib.util.spec_from_file_location("password_setup",
    Path(__file__).resolve().parents[1] / "scripts/set_demo_password.py")
assert spec is not None and spec.loader is not None
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_install_uses_stdin_without_echo_or_local_logs(capsys):
    secret = "PRIVATE-test-fixture"
    with patch.object(setup.subprocess, "run") as run:
        run.return_value = CompletedProcess([], 0, secret, "")
        setup.install("DEMO_PASSWORD", secret)
    args, kwargs = run.call_args
    assert secret not in str(args) + str(kwargs["env"])
    assert kwargs["input"] == secret + "\n"
    assert kwargs["env"]["WRANGLER_LOG_PATH"] == os.devnull
    assert capsys.readouterr().out == ""


def test_noninteractive_terminal_refused_before_reading_password(capsys):
    with patch.object(setup.sys.stdin, "isatty", return_value=False), patch.object(setup, "getpass") as prompt:
        assert setup.main() == 1
    prompt.assert_not_called()


def test_success_sets_password_and_new_key_without_display(capsys):
    with patch.object(setup.sys.stdin, "isatty", return_value=True), patch.object(setup.sys.stderr, "isatty", return_value=True), \
         patch.object(Path, "is_file", return_value=True), patch.object(setup, "getpass", return_value="PRIVATE-password"), \
         patch.object(setup, "install") as install:
        assert setup.main() == 0
    assert [call.args[0] for call in install.call_args_list] == ["DEMO_PASSWORD", "DEMO_AUTH_KEY"]
    assert len(install.call_args_list[1].args[1]) == 64
    assert "PRIVATE" not in capsys.readouterr().out
