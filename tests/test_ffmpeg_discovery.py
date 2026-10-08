from pathlib import Path

from multiview_sync_player import config


def test_windows_source_checkout_finds_copied_media_tools(tmp_path, monkeypatch):
    module = tmp_path / 'multiview_sync_player' / 'config.py'
    module.parent.mkdir()
    tools = tmp_path / 'packaging' / 'bin'
    tools.mkdir(parents=True)
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        (tools / name).write_bytes(b'MZ')
    monkeypatch.setattr(config, '__file__', str(module))
    monkeypatch.setattr(config.sys, 'platform', 'win32')
    monkeypatch.setattr(config.sys, 'frozen', False, raising=False)
    monkeypatch.setattr(config.shutil, 'which', lambda _: None)
    resolved = config._find_ffmpeg()
    assert Path(resolved) == tools / 'ffmpeg.exe'
    monkeypatch.setattr(config, 'FFMPEG_PATH', resolved)
    assert Path(config._find_ffprobe()) == tools / 'ffprobe.exe'


def test_frozen_tools_take_priority_over_source_and_path(tmp_path, monkeypatch):
    bundle = tmp_path / '_internal'
    (bundle / 'bin').mkdir(parents=True)
    (bundle / 'bin' / 'ffmpeg.exe').write_bytes(b'MZ')
    monkeypatch.setattr(config.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(config.sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr(config.shutil, 'which', lambda _: 'system-ffmpeg')
    assert Path(config._find_ffmpeg()) == bundle / 'bin' / 'ffmpeg.exe'


def test_linux_source_discovery_does_not_select_windows_executable(tmp_path, monkeypatch):
    module = tmp_path / 'multiview_sync_player' / 'config.py'
    module.parent.mkdir()
    tools = tmp_path / 'packaging' / 'bin'
    tools.mkdir(parents=True)
    (tools / 'ffmpeg.exe').write_bytes(b'MZ')
    monkeypatch.setattr(config, '__file__', str(module))
    monkeypatch.setattr(config.sys, 'platform', 'linux')
    monkeypatch.setattr(config.sys, 'frozen', False, raising=False)
    monkeypatch.setattr(config.shutil, 'which', lambda _: '/usr/bin/ffmpeg')
    assert config._find_ffmpeg() == '/usr/bin/ffmpeg'
