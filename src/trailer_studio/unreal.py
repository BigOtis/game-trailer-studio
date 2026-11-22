from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .media import ffmpeg
from .models import Recipe, Take, identifier
from .workspace import read_json, write_json


def bundled(name: str) -> Path:
    checkout = Path(__file__).resolve().parents[2]
    path = checkout / ("unreal" if name == "TrailerStudio" else "skills") / name
    if (checkout / "pyproject.toml").is_file() and path.is_dir():
        return path
    installed = Path(__file__).parent / "bundled" / name
    if installed.is_dir():
        return installed
    if not path.is_dir():
        raise FileNotFoundError(f"Bundled {name} is missing; reinstall the package")
    return path


def editor(engine: Path) -> Path:
    if sys.platform == "win32":
        return engine / "Engine/Binaries/Win64/UnrealEditor.exe"
    if sys.platform == "darwin":
        return engine / "Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor"
    return engine / "Engine/Binaries/Linux/UnrealEditor"


def resolve_engine(uproject: Path, explicit: Path | None = None) -> Path:
    association = read_json(uproject).get("EngineAssociation", "")
    candidates = []
    if explicit:
        candidates.append(explicit)
    elif os.environ.get("UE_ROOT"):
        candidates.append(Path(os.environ["UE_ROOT"]))
    elif sys.platform == "win32":
        import winreg

        for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Epic Games\Unreal Engine\Builds")]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    candidates.append(Path(winreg.QueryValueEx(handle, association)[0]))
            except OSError:
                pass
        if association:
            candidates.append(
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "Epic Games"
                / ("UE_" + association)
            )
    elif sys.platform == "darwin" and association:
        candidates.append(Path("/Users/Shared/Epic Games") / ("UE_" + association))
    for candidate in candidates:
        candidate = candidate.resolve()
        if editor(candidate).is_file():
            return candidate
    raise FileNotFoundError("Could not resolve this project's Unreal install; pass --engine or set UE_ROOT")


def install_plugin(uproject: Path):
    uproject = uproject.resolve()
    data = read_json(uproject)
    destination = uproject.parent / "Plugins/TrailerStudio"
    if destination.exists():
        raise FileExistsError(
            "TrailerStudio already exists. Back it up/remove it explicitly before updating."
        )
    source = bundled("TrailerStudio")
    # Only authored source/config; never copy Binaries, Intermediate or user assets.
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("Binaries", "Intermediate", "Saved"))
    plugins = data.setdefault("Plugins", [])
    entry = next((p for p in plugins if p.get("Name") == "TrailerStudio"), None)
    if entry:
        entry["Enabled"] = True
    else:
        plugins.append(dict(Name="TrailerStudio", Enabled=True))
    backup = uproject.with_suffix(".uproject.before-trailer-studio")
    if not backup.exists():
        shutil.copy2(uproject, backup)
    write_json(uproject, data)
    return dict(plugin=str(destination), project=str(uproject), backup=str(backup))


def fixture(destination: Path, engine: Path) -> Path:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    version = read_json(engine / "Engine/Build/Build.version")
    uproject = destination / "TrailerFixture.uproject"
    write_json(
        uproject,
        dict(
            FileVersion=3,
            EngineAssociation=f"{version['MajorVersion']}.{version['MinorVersion']}",
            Modules=[dict(Name="TrailerFixture", Type="Runtime", LoadingPhase="Default")],
        ),
    )
    source = destination / "Source"
    module = source / "TrailerFixture"
    module.mkdir(parents=True)
    (module / "TrailerFixture.cpp").write_text(
        '#include "Modules/ModuleManager.h"\nIMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, TrailerFixture, "TrailerFixture");\n',
        encoding="utf-8",
    )
    (module / "TrailerFixture.Build.cs").write_text(
        """using UnrealBuildTool;
public class TrailerFixture : ModuleRules {
 public TrailerFixture(ReadOnlyTargetRules Target):base(Target) {
  PCHUsage=PCHUsageMode.UseExplicitOrSharedPCHs;
  PublicDependencyModuleNames.AddRange(new[]{"Core","CoreUObject","Engine"});
  if(Target.Configuration!=UnrealTargetConfiguration.Shipping && Target.Configuration!=UnrealTargetConfiguration.Test)
   PrivateDependencyModuleNames.Add("TrailerStudio");
 }
}
""",
        encoding="utf-8",
    )
    (module / "TrailerFixtureGameMode.h").write_text(
        """#pragma once
#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "TrailerFixtureGameMode.generated.h"
UCLASS()
class ATrailerFixtureGameMode : public AGameModeBase {
 GENERATED_BODY()
public:
 virtual void StartPlay() override;
 UFUNCTION() void HandleStudioCommand(const FString& Name,const FString& ArgumentsJson);
};
""",
        encoding="utf-8",
    )
    (module / "TrailerFixtureGameMode.cpp").write_text(
        """#include "TrailerFixtureGameMode.h"
#include "Engine/GameInstance.h"
#if !UE_BUILD_SHIPPING && !UE_BUILD_TEST
#include "TrailerStudioSubsystem.h"
#endif
void ATrailerFixtureGameMode::StartPlay() {
 Super::StartPlay();
#if !UE_BUILD_SHIPPING && !UE_BUILD_TEST
 if(auto* Studio=GetGameInstance()->GetSubsystem<UTrailerStudioSubsystem>();Studio&&Studio->IsEnabled()) {
  Studio->RegisterSubject(TEXT("early_subject"),this);
  Studio->SetProjectStateJson(TEXT("{\\"fixture_begin_play\\":true}"));
  Studio->OnProjectCommand.AddDynamic(this,&ATrailerFixtureGameMode::HandleStudioCommand);
 }
#endif
}
void ATrailerFixtureGameMode::HandleStudioCommand(const FString& Name,const FString&) {
#if !UE_BUILD_SHIPPING && !UE_BUILD_TEST
 if(Name==TEXT("fixture_observe"))GetGameInstance()->GetSubsystem<UTrailerStudioSubsystem>()->SetProjectStateJson(TEXT("{\\"fixture_begin_play\\":true,\\"command_seen\\":true}"));
#endif
}
""",
        encoding="utf-8",
    )
    for suffix, kind in [("", "Game"), ("Editor", "Editor")]:
        (source / f"TrailerFixture{suffix}.Target.cs").write_text(
            f"""using UnrealBuildTool;
public class TrailerFixture{suffix}Target : TargetRules {{
 public TrailerFixture{suffix}Target(TargetInfo Target):base(Target) {{
  Type=TargetType.{kind};DefaultBuildSettings=BuildSettingsVersion.Latest;
  IncludeOrderVersion=EngineIncludeOrderVersion.Latest;ExtraModuleNames.Add("TrailerFixture");
 }}
}}
""",
            encoding="utf-8",
        )
    config = destination / "Config"
    config.mkdir()
    (config / "DefaultEngine.ini").write_text(
        """[/Script/EngineSettings.GameMapsSettings]
GameDefaultMap=/Engine/Maps/Entry
EditorStartupMap=/Engine/Maps/Entry
GlobalDefaultGameMode=/Script/TrailerFixture.TrailerFixtureGameMode
[/Script/Engine.RendererSettings]
r.DynamicGlobalIlluminationMethod=0
r.ReflectionMethod=0
""",
        encoding="utf-8",
    )
    install_plugin(uproject)
    return uproject


def build(uproject: Path, engine: Path, log: Path):
    name = uproject.stem + "Editor"
    platform = {"win32": "Win64", "darwin": "Mac"}.get(sys.platform, "Linux")
    entry = (
        engine
        / "Engine/Build/BatchFiles"
        / ({"win32": "Build.bat", "darwin": "Mac/Build.sh"}.get(sys.platform, "Linux/Build.sh"))
    )
    args = [
        str(entry),
        name,
        platform,
        "Development",
        str(uproject.resolve()),
        "-WaitMutex",
        "-NoHotReloadFromIDE",
        "-MaxParallelActions=2",
    ]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Unreal build failed; see {log}")
    return dict(passed=True, log=str(log))


def launch(root: Path, uproject: Path, engine: Path, map_name: str, demo=False, timeout=120):
    from .workspace import project

    config = project(root)
    name = uuid.uuid4().hex
    session = root / ".trailer-studio/ue-sessions" / name
    session.mkdir(parents=True)
    bridge = session / "bridge"
    args = [
        str(editor(engine)),
        str(uproject.resolve()),
        map_name,
        "-game",
        "-TrailerStudio",
        "-TrailerSession=" + name,
        "-TrailerBridgeDir=" + str(bridge),
        "-TrailerOutput=" + str(root / "takes"),
        "-TrailerFFmpeg=" + ffmpeg(),
        "-TrailerFPS=" + str(config.fps),
        "-TrailerCodec=" + config.codec,
        "-UserDir=" + str(session / "User"),
        "-abslog=" + str(session / "game.log"),
        "-Windowed",
        "-ResX=" + str(config.width),
        "-ResY=" + str(config.height),
        "-NoSplash",
        "-Unattended",
        "-RenderOffscreen",
    ]
    if demo:
        args.append("-TrailerDemo")
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    child = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    import psutil

    record = dict(
        version=1,
        session=name,
        pid=child.pid,
        project=str(uproject.resolve()),
        engine=str(engine),
        bridge=str(bridge),
        arguments=args,
        output_root=str((root / "takes").resolve()),
        created_at=psutil.Process(child.pid).create_time(),
    )
    manifest = session / "session.json"
    write_json(manifest, record)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if child.poll() is not None:
            raise RuntimeError(f"Game exited during startup; see {session / 'game.log'}")
        try:
            client = Bridge(manifest)
            if client.state().get("ready"):
                return manifest
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    # A timed-out owned launch can be terminated; do not enumerate/stop unrelated engines.
    child.terminate()
    raise TimeoutError(f"No matching bridge from the owned game; see {session / 'game.log'}")


class Bridge:
    def __init__(self, manifest: Path):
        self.manifest = manifest.resolve()
        self.record = read_json(self.manifest)
        self.path = Path(self.record["bridge"])
        self.pid = self.record["pid"]
        self.session = self.record["session"]
        identifier(self.session)
        self.state()

    def state(self):
        # Retry atomic-replacement sharing collisions, never a command or side effect.
        for _ in range(8):
            try:
                state = read_json(self.path / "state.json")
                break
            except (OSError, json.JSONDecodeError):
                time.sleep(0.025)
        else:
            raise FileNotFoundError("Bridge state unavailable")
        if state.get("pid") != self.pid or state.get("session") != self.session or state.get("version") != 1:
            raise ValueError("Bridge belongs to a different process/session/protocol")
        return state

    def command(self, command: str, arguments=None, timeout=45):
        self.state()
        request_id = uuid.uuid4().hex
        payload = dict(
            version=1,
            id=request_id,
            session=self.session,
            expected_pid=self.pid,
            command=command,
            arguments=arguments or {},
        )
        write_json(self.path / "inbox" / (request_id + ".json"), payload)
        deadline = time.monotonic() + timeout
        response = self.path / "outbox" / (request_id + ".json")
        while time.monotonic() < deadline:
            try:
                result = read_json(response)
            except (OSError, json.JSONDecodeError):
                time.sleep(0.025)
                continue
            if result.get("id") != request_id:
                raise ValueError("Mismatched command acknowledgement")
            if not result.get("ok"):
                raise ValueError(result.get("error", "Game rejected the command"))
            return result.get("result", {})
        raise TimeoutError("No command acknowledgement; not retried because it may have executed")

    def wait(self, path: str, equals, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.state()
            value = state
            for key in path.split("."):
                value = value.get(key) if isinstance(value, dict) else None
            if value == equals:
                return state
            time.sleep(0.1)
        raise TimeoutError(f"Observed state {path} did not become {equals!r}")


def stop_session(manifest: Path):
    import psutil

    record = read_json(manifest)
    try:
        process = psutil.Process(record["pid"])
    except psutil.NoSuchProcess:
        return {"stopped": True, "already_exited": True}
    if (
        abs(process.create_time() - record.get("created_at", -1)) > 0.01
        or "-TrailerSession=" + record["session"] not in process.cmdline()
    ):
        raise ValueError("Refusing to stop a process that does not match the launched session")
    try:
        Bridge(manifest).command("shutdown", timeout=45)
        process.wait(timeout=15)
    except (TimeoutError, OSError, psutil.TimeoutExpired):
        # Creation time and launch nonce were verified above; only this owned process is terminated.
        process.terminate()
        process.wait(timeout=15)
    return {"stopped": True, "pid": record["pid"]}


def capture_recipe(root: Path, recipe_path: Path, manifest: Path, take_id: str):
    from .media import probe

    identifier(take_id)
    if (root / "takes" / take_id).exists():
        raise FileExistsError("Use a new take ID")
    recipe = Recipe.model_validate(read_json(recipe_path))
    client = Bridge(manifest)
    if Path(client.record.get("output_root", "")).resolve() != (root / "takes").resolve():
        raise ValueError("This game session records into a different workspace")
    if Path(client.record["bridge"]).resolve() == root.resolve():
        raise ValueError("Bridge and media workspace cannot be the same directory")
    result = dict(take=take_id, recipe=recipe.model_dump(), passed=False, steps=[])
    recording = False
    good = False

    def step(item):
        if item.command:
            client.command(item.command, item.arguments)
        elif item.wait:
            client.wait(item.wait.path, item.wait.equals, item.wait.timeout)
        elif item.hold is not None:
            time.sleep(item.hold)
        else:
            client.command("mark", {"label": item.mark})
        result["steps"].append(dict(step=item.model_dump(exclude_none=True), observed=client.state()))

    try:
        for item in recipe.setup:
            step(item)
        client.command("capture_start", {"take": take_id})
        recording = True
        for item in recipe.record:
            step(item)
        result["passed"] = True
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        if recording:
            client.command("capture_stop", timeout=60)
        destination = root / "takes" / take_id
        if destination.is_dir():
            write_json(destination / "recipe-result.json", result)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not (destination / "audio.wav").is_file():
                time.sleep(0.1)
            capture = (
                read_json(destination / "capture.json") if (destination / "capture.json").is_file() else {}
            )
            good = result["passed"] and capture.get("passed") and (destination / "audio.wav").is_file()
            if good:
                probe(destination / "audio.wav")
            take = Take(
                id=take_id,
                video=f"takes/{take_id}/video.mp4",
                audio=f"takes/{take_id}/audio.wav",
                accepted=bool(good),
                build=recipe.build,
                notes=recipe.purpose + ("" if good else " / Rejected: inspect capture and recipe results"),
            )
            write_json(destination / "take.json", take.model_dump())
    if not result["passed"] or not good:
        raise ValueError("Capture did not complete; rejected take retained for review")
    return dict(passed=True, take=take_id, directory=str(destination))
