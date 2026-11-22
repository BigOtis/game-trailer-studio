# Unreal Engine 5 integration

## Prerequisites and supported launch mode

Use a locally installed licensed UE5 engine and its normal C++ build toolchain. The CLI resolves
`--engine`, then `UE_ROOT`, then registered/versioned platform installs. A registered project GUID on
Windows is looked up under `HKCU/Software/Epic Games/Unreal Engine/Builds`. No engine path is hardcoded.

The native plugin is verified on Windows UE5.9. It uses stock viewport/mixer APIs and does not require
engine modifications, editor Python, MCP or paid recording software. Other engines/platforms need
their own compile/render validation. Use standalone Development `UnrealEditor -game` or your own
packaged Development executable with the documented arguments. Automated cooking/packaging of your
game is outside the initial launcher.

`ue install --project MyGame.uproject` adds the plugin and a descriptor backup. Close your editor
before building if its module DLL would be locked. Build your normal editor target, or use `ue build`
for conventional `<ProjectName>Editor` targets. Reinstalling over an existing plugin is deliberately
refused: back up your changes and update it explicitly.

## Capture-only game hooks

In your game's capture integration actor/Blueprint:

1. Get Game Instance Subsystem → **TrailerStudioSubsystem**.
2. Check **Is Enabled**. Ordinary game launches have no active capture bridge.
3. Bind **On Project Command**. Inputs are `Name` and a JSON object string `ArgumentsJson`.
4. Implement only the game-specific commands your shot recipes need: for example,
   `load_capture_checkpoint`, `open_chat` or a normal player instruction transport.
5. Publish observable state via **Set Project State Json**, for example
   `{"checkpoint_ready":true,"box_is_held":false}`.

For projects without a Blueprint JSON parser, dispatch by command name and parse arguments in your
C++ integration. `SetProjectStateJson` validates an object and returns false on invalid JSON.
An acknowledged `project` command means dispatched to your handler, **not task completed**.
Recipes separately wait for real state such as `project.box_is_held == true`. If no handler is bound,
the command fails instead of pretending it worked.

Minimal C++ integration pattern (inside your own actor, with its own lifecycle handling):

```cpp
// MyCaptureActor.h
UFUNCTION()
void HandleTrailerCommand(const FString& Name, const FString& ArgumentsJson);

// BeginPlay
auto* Studio = GetGameInstance()->GetSubsystem<UTrailerStudioSubsystem>();
if (Studio && Studio->IsEnabled()) {
    Studio->OnProjectCommand.AddDynamic(this, &AMyCaptureActor::HandleTrailerCommand);
    Studio->RegisterSubject(TEXT("companion"), CompanionActor);
}
// When actual game state changes, publish a compact observed JSON state.
// Do not set box_is_held merely because a command was requested.
```

Add `TrailerStudio` to your capture integration module's dependencies only in non-Shipping/Test
targets and guard its includes/calls accordingly. A Blueprint-only reference should live in tooling
you exclude from your shipping cook. The plugin module descriptor itself excludes Shipping/Test.

## Subjects and input

Call `RegisterSubject("companion", Actor)` for camera/staging subjects. Alternatively, add actor tags
such as `TrailerSubject:companion` before launch; the plugin scans tags when the game world begins.
Call `subjects_refresh` after spawning additional tagged actors. Snapshots contain only registered
subjects, rather than a full actor/object registry.

`camera_set` and `camera_move` accept a `location` object, `rotation` object (`pitch`, `yaw`, `roll`),
`fov`, and optional registered `track` ID. `camera_move` also accepts `duration` in seconds. Moves
use a smoothstep position interpolation, with orientation tracking the subject or interpolating to
the requested rotation. `camera_restore` restores the previous player view target.

`actor_set` is an explicit staging operation for a registered subject. It preserves omitted transform
fields, teleports the actual actor, clears velocities and wakes simulated bodies. Use it between takes.
It does not claim that the game completed a requested task. There is no arbitrary console/Python
execution endpoint.

`key` routes a real player key event. Use press and release explicitly. `type_text` sends real Slate
character events to an already focused game widget and optionally Enter. Opening/focusing your chat
UI is game-specific; use your existing key binding or project hook. Send short chunks separated by
`hold` recipe steps when active typing should be visible.

## Recording behavior

`capture_start` starts the rendered viewport observer and master-submix recorder. The native queue is
bounded. FFmpeg runs as a child with an explicit executable path; CPU H.264 is default, NVENC optional.
Frames are timestamped in wall-clock time and repeated to fill the requested output cadence when
needed. Simulation speed and game FPS settings are not changed.

`capture_stop` drains frames, finishes/validates the encoder return code and writes metadata. It stops
the stock audio-mixer recording and writes PCM WAV directly into the validated take folder, avoiding
version-specific Blueprint WAV-export path restrictions. Audio channels/rate come from the actual
mixer; the editor resamples the mix for delivery. Unfocused audio volume is restored on cleanup.

Do not record another submix capture concurrently: the master recorder is a shared game resource.
The initial implementation retains native audio in memory until stop; use sensible take lengths and
monitor memory for long recordings. World travel ends an active recording; avoid changing levels
inside a take. Measured audio/video offsets can be recorded in `take.json`'s `audio_offset`.

## Run the fixture

The fixture uses only engine basic shapes, real physics, a moving camera and a generated procedural
test tone. It needs no game assets, scripts, network service or model. Generated fixture files and
all recordings remain outside source control.

```sh
uv run python scripts/verify_ue5.py --engine "C:/Program Files/Epic Games/UE_5.9" --output .artifacts/ue-proof
```

The script creates/builds a fresh minimal project, launches an isolated Development game, captures
the example recipe, verifies native audio and picture, renders a short cut, makes a contact sheet,
and stops only the process it launched. Inspect `evidence/verification.json` and the actual frames.
The procedural test tone is identified as a fixture sound, never passed off as game dialogue.
