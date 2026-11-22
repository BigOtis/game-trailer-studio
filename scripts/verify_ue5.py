"""Opt-in real UE capture proof. Creates its own source fixture/profile and stops only its process."""

import argparse
import array
import hashlib
import json
import shutil
import time
from pathlib import Path

import av

from trailer_studio.media import verify
from trailer_studio.render import render, review
from trailer_studio.unreal import Bridge, build, capture_recipe, fixture, launch, stop_session
from trailer_studio.workspace import initialize, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise FileExistsError("Choose a fresh integration output directory")
    out.mkdir(parents=True)
    evidence = out / "evidence"
    evidence.mkdir()
    root = initialize(out / "trailer with spaces", "UE5 Native Fixture", width=640, height=360)
    uproject = fixture(out / "project with spaces", args.engine.resolve())
    report = dict(passed=False, engine=read_json(args.engine / "Engine/Build/Build.version"), checks=[])
    manifest = None
    try:
        build(uproject, args.engine.resolve(), evidence / "native-build.log")
        report["checks"].append("Native plugin and independent game project compiled")
        manifest = launch(root, uproject, args.engine.resolve(), "/Engine/Maps/Entry", demo=True)
        client = Bridge(manifest)
        report["initial_state"] = client.state()
        assert report["initial_state"]["project"]["fixture_begin_play"]
        assert "early_subject" in report["initial_state"]["subjects"]
        client.command("project", {"name": "fixture_observe", "payload": {}})
        client.wait("project.command_seen", True, 5)
        report["checks"].append("BeginPlay registration/state and real project-command hook work")
        time.sleep(1)
        source = Path(__file__).resolve().parents[1] / "examples/ue5/demo-recipe.json"
        recipe = root / "recipes/demo.json"
        shutil.copy2(source, recipe)
        capture_recipe(root, recipe, manifest, "ue_fixture_01")
        destination = root / "takes/ue_fixture_01"
        metadata = read_json(destination / "capture.json")
        assert metadata["passed"] and metadata["audio_written"] and metadata["captured_frames"] > 2
        raw = verify(destination / "video.mp4", fps=30, require_audio=False)
        assert raw["passed"] and raw["frames"] == metadata["encoded_frames"], raw
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        peak = 0
        with av.open(str(destination / "audio.wav")) as container:
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    values = array.array("h", bytes(converted.planes[0]))
                    peak = max(peak, max(abs(v) for v in values))
        assert peak > 100, "Native recording is silent"
        observed = read_json(destination / "recipe-result.json")
        first = observed["steps"][1]["observed"]["subjects"]["ball"]["location"]["z"]
        last = client.state()["subjects"]["ball"]["location"]["z"]
        assert first - last > 100, "Real physics sphere did not fall"
        final_state = client.state()
        assert not final_state["camera"]["moving"]
        assert abs(final_state["camera"]["location"]["x"] + 400) < 1
        frames = []
        with av.open(str(destination / "video.mp4")) as container:
            for frame in container.decode(video=0):
                if frame.time is not None and (not frames or (len(frames) == 1 and frame.time >= 2)):
                    image = frame.to_image()
                    image.save(evidence / ("native-start.png" if not frames else "native-end.png"))
                    frames.append(hashlib.sha256(image.tobytes()).hexdigest())
                if len(frames) == 2:
                    break
        assert len(frames) == 2 and frames[0] != frames[1], "Rendered camera frames did not change"
        report["checks"] += [
            "Actual viewport frames captured and decoded",
            "Native master audio is audible",
            "Observed physics sphere fall",
            "Camera reaches requested end position",
            "Rendered frames change during camera move",
        ]
        report["capture"] = metadata
        report["audio_peak_s16"] = peak
        report["physics_ball_z"] = [first, last]
        write_json(
            root / "edits/native.json",
            dict(
                name="UE5 real capture proof",
                expected_duration=4,
                shots=[
                    dict(
                        kind="card",
                        duration=1,
                        title="UE5 Native Fixture",
                        subtitle="Real viewport / native test tone",
                    ),
                    dict(
                        take="ue_fixture_01",
                        source_in=0.2,
                        duration=3,
                        purpose="Actual camera, physics and native audio",
                    ),
                ],
            ),
        )
        result = render(root, root / "edits/native.json", Path("exports/native-v1.mp4"))
        review(root, root / "edits/native.json", Path("exports/native-v1.mp4"), Path("review/index.html"))
        report["export"] = result["verification"]
        report["checks"].append("Captured source becomes a verified four-second edit/review")
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        if manifest:
            report["cleanup"] = stop_session(manifest)
        write_json(evidence / "verification.json", report)
    print(
        json.dumps(
            {"passed": report["passed"], "checks": report["checks"], "evidence": str(evidence)}, indent=2
        )
    )


if __name__ == "__main__":
    main()
