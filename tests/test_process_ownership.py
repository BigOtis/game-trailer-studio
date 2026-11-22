import pytest

from trailer_studio.unreal import stop_session
from trailer_studio.workspace import write_json


def test_stopping_session_rejects_reused_pid_before_any_signal(tmp_path, monkeypatch):
    class OtherProcess:
        def create_time(self):
            return 999

        def cmdline(self):
            return ["UnrealEditor", "-TrailerSession=expected"]

        def terminate(self):
            pytest.fail("A reused PID must never receive a signal")

    monkeypatch.setattr("psutil.Process", lambda pid: OtherProcess())
    manifest = tmp_path / "session.json"
    write_json(manifest, {"pid": 123, "created_at": 100, "session": "expected"})
    with pytest.raises(ValueError, match="does not match"):
        stop_session(manifest)
