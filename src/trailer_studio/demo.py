from __future__ import annotations

from pathlib import Path

from .media import ffmpeg, run
from .workspace import import_take, project, write_json


def demo(root: Path):
    config = project(root)
    generated = root / ".trailer-studio/synthetic-demo"
    generated.mkdir(parents=True, exist_ok=True)
    for name, pattern, tone in [("demo-pattern", "testsrc2", 440), ("demo-grid", "smptebars", 660)]:
        if (root / "takes" / name).exists():
            continue
        video, audio = generated / (name + ".mp4"), generated / (name + ".wav")
        run(
            [
                ffmpeg(),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"{pattern}=size={config.width}x{config.height}:rate={config.fps}",
                "-t",
                "5",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-threads",
                "2",
                "-pix_fmt",
                "yuv420p",
                str(video),
            ]
        )
        run(
            [
                ffmpeg(),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={tone}:sample_rate=48000",
                "-t",
                "5",
                "-c:a",
                "pcm_s16le",
                str(audio),
            ]
        )
        import_take(
            root,
            name,
            video,
            audio,
            provenance="synthetic-test",
            notes="Generated test pattern; NOT gameplay",
        )
    edit = dict(
        version=1,
        name="Synthetic toolkit demonstration",
        expected_duration=10,
        shots=[
            dict(
                kind="card",
                title=config.name,
                subtitle="SYNTHETIC TEST / NOT GAMEPLAY",
                duration=2,
                purpose="Editorial title",
            ),
            dict(take="demo-pattern", source_in=0.5, duration=4, purpose="Synthetic moving test pattern"),
            dict(take="demo-grid", source_in=1, duration=3, purpose="Synthetic colour bars"),
            dict(
                kind="card", title="Your gameplay goes here", subtitle="Review, direct, iterate", duration=1
            ),
        ],
        captions=[dict(start=2, end=5, text="Synthetic demo footage — replace with your captured takes.")],
    )
    write_json(root / "edits/demo.json", edit)
    return dict(edit=str(root / "edits/demo.json"), provenance="synthetic-test", duration=10)
