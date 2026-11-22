---
name: game-trailer-production
description: Capture real gameplay and create or refresh editable game trailers with Game Trailer Studio, including its Unreal Engine 5 adapter, shot recipes and versioned edit manifests.
---

# Game trailer production

Keep the developer in control of the story, audience, tone, runtime and final selection. Read the brief,
project instructions and current edit before changing the production. Preserve choices already made;
ask only when missing direction materially affects the result.

Use the installed `trailer-studio --help` and the toolkit's README. Bootstrap dependencies with
`uv sync --extra dev` in a source checkout, or install its wheel. `trailer-studio doctor` checks the
managed FFmpeg and media stack. The developer supplies their licensed UE installation.

## Set up

Create a separate trailer workspace and capture profile. Check the project, session and process ID
before sending commands. Keep human saves and playthroughs separate. Original recordings are inputs,
not disposable intermediates.

For UE5, install the bundled plugin using `trailer-studio ue install`, build the Development editor,
and launch an isolated opt-in session using `trailer-studio ue launch`. Read the
[UE5 integration guide](https://github.com/BigOtis/game-trailer-studio/blob/main/docs/ue5.md)
when wiring game-specific hooks. The native plugin supplies capture, cameras, markers,
registered subjects, key/character input and state. Game-specific goals/checkpoints require the
developer's Blueprint/C++ project-command handler and published state; never invent an adapter.

## Record

Define shots by their purpose, checkpoint, subject, camera transform/FOV/movement, real player input
and observed completion condition. Treat coordinates as hints after layout changes. Verify floor
clearance, collision, camera framing and the actual rendered result.

Run a recipe into a NEW take ID. Send input through the real game path. Wait for observed state rather
than just a fixed sleep or empty action queue. Leave handles around useful action. Preserve video,
native audio, metadata, events and failed attempts. Mark unsuitable takes rejected. Label staged
dialogue, editorial transitions and synthetic test footage accurately.

## Edit

Use take IDs, source in-points, durations, crops, captions and audio treatment in an edit JSON file.
Keep request → response → action → outcome → reaction legible. Shorten travel/waiting at clear
boundaries. Show typing when it explains gameplay; follow the user's direction about hiding
preparation commands for staged trailer moments.

Recorded heard dialogue is the caption-text authority. Align the selected take's own audio, and flag
estimates for review. Keep music under speech. A master submix is not an isolated voice stem.

Render a new export using `trailer-studio render`. Generate `trailer-studio review` and watch it.
Inspect contact sheets, contact/motion, complete lines, sound sync, result visibility and framing.
Apply directing notes while retaining previous edits and exports.

## Refresh

Separate edit-only revisions from shots needing new capture. Record the new build/settings, recheck
checkpoints and camera paths, and capture affected recipes under new take IDs. Dialogue, navigation,
physics and timing may differ. Re-select source ranges and captions rather than blindly reusing old
in-points. Use `retarget` only with ranges that fit the reviewed new take.

The renderer hashes source bytes and settings for its caches. Preserve that behavior when extending
it. Verify actual exported frames, cadence, audio and full decode with `trailer-studio verify`.
Report repeated rendered frames, upscales and remaining review limitations accurately.

Local production does not itself authorize uploading footage or publishing a trailer. Follow the
user's actual scope for external actions. Keep the brief, sources, edit and delivery inspectable.
