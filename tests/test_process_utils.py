import subprocess

from multiview_sync_player import process_utils


def test_windows_hidden_subprocess_flags(monkeypatch):
    monkeypatch.setattr(process_utils.sys, "platform", "win32")
    options = process_utils.hidden_process_kwargs()
    assert options["shell"] is False
    assert options["stdin"] is subprocess.DEVNULL
    assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert options["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert options["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_linux_has_no_windows_subprocess_flags(monkeypatch):
    monkeypatch.setattr(process_utils.sys, "platform", "linux")
    options = process_utils.hidden_process_kwargs()
    assert options == {"stdin": subprocess.DEVNULL, "shell": False}
