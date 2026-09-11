from multiview_sync_player import backend


def test_auto_falls_back_until_mpv_accuracy_is_verified(monkeypatch):
    monkeypatch.setattr(
        backend, "detect_mpv_capability",
        lambda: backend.BackendCapability(True, True, False, False))
    decision = backend.choose_backend("auto")
    assert decision.active == "opencv"
    assert decision.mode == "Strict"
    assert "frame-accuracy" in decision.reason


def test_explicit_gpu_is_unverified_prototype(monkeypatch):
    monkeypatch.setattr(
        backend, "detect_mpv_capability",
        lambda: backend.BackendCapability(True, True, False, False))
    decision = backend.choose_backend("gpu")
    assert decision.active == "mpv"
    assert decision.mode == "GPU Prototype"


def test_gpu_falls_back_when_mpv_unavailable(monkeypatch):
    monkeypatch.setattr(
        backend, "detect_mpv_capability",
        lambda: backend.BackendCapability(
            False, False, False, False, "missing"))
    assert backend.choose_backend("gpu").active == "opencv"


def test_gpu_target_mapping():
    assert backend.frame_to_time(0, 25.0) == 0.0
    assert backend.frame_to_time(125, 25.0) == 5.0


def test_native_wayland_wid_embedding_is_not_claimed(monkeypatch):
    monkeypatch.setattr(backend.sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(backend, "_import_mpv", lambda: object())
    capability = backend.detect_mpv_capability()
    assert capability.available
    assert not capability.embedded_render
    assert not capability.wayland_native
