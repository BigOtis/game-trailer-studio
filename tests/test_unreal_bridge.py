import threading
import time

import pytest

from trailer_studio.unreal import Bridge, install_plugin, resolve_engine
from trailer_studio.workspace import read_json, write_json


def session(tmp_path):
    bridge = tmp_path / "bridge"
    (bridge / "inbox").mkdir(parents=True)
    (bridge / "outbox").mkdir()
    write_json(bridge / "state.json", dict(version=1, pid=123, session="fixture", ready=True))
    manifest = tmp_path / "session.json"
    write_json(manifest, dict(bridge=str(bridge), pid=123, session="fixture"))
    return Bridge(manifest), bridge


def test_bridge_binds_process_and_never_retries_a_timed_out_command(tmp_path):
    client, directory = session(tmp_path)
    with pytest.raises(TimeoutError):
        client.command("project", {"name": "do-once"}, timeout=0.05)
    assert len(list((directory / "inbox").glob("*.json"))) == 1
    write_json(directory / "state.json", dict(version=1, pid=999, session="fixture"))
    with pytest.raises(ValueError, match="different process"):
        client.state()


def test_bridge_reads_matching_acknowledgement(tmp_path):
    client, directory = session(tmp_path)

    def respond():
        end = time.monotonic() + 2
        while time.monotonic() < end:
            files = list((directory / "inbox").glob("*.json"))
            if files:
                command = read_json(files[0])
                write_json(
                    directory / "outbox" / (command["id"] + ".json"),
                    dict(id=command["id"], ok=True, result={"value": 42}),
                )
                return
            time.sleep(0.01)

    thread = threading.Thread(target=respond)
    thread.start()
    assert client.command("ping")["value"] == 42
    thread.join()


def test_install_preserves_project_plugins_and_excludes_build_outputs(tmp_path):
    project = tmp_path / "Example.uproject"
    write_json(project, dict(EngineAssociation="5.9", Plugins=[dict(Name="Other", Enabled=True)]))
    install_plugin(project)
    data = read_json(project)
    assert data["Plugins"][0] == {"Name": "Other", "Enabled": True}
    plugin = tmp_path / "Plugins/TrailerStudio"
    descriptor = read_json(plugin / "TrailerStudio.uplugin")
    assert descriptor["Modules"][0]["TargetConfigurationDenyList"] == ["Shipping", "Test"]
    assert not list(plugin.rglob("*.dll"))
    with pytest.raises(FileExistsError):
        install_plugin(project)
    assert project.with_suffix(".uproject.before-trailer-studio").is_file()


def test_explicit_engine_resolution_uses_project_and_executable(tmp_path):
    from trailer_studio.unreal import editor

    project = tmp_path / "Example.uproject"
    write_json(project, {"EngineAssociation": "{a-registered-build-guid}"})
    engine = tmp_path / "EngineInstall"
    binary = editor(engine)
    binary.parent.mkdir(parents=True)
    binary.touch()
    assert resolve_engine(project, engine) == engine.resolve()
