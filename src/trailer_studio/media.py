from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import av
import imageio_ffmpeg


def ffmpeg() -> str:
    override = os.environ.get("TRAILER_STUDIO_FFMPEG")
    path = override or imageio_ffmpeg.get_ffmpeg_exe()
    if not Path(path).is_file():
        path = shutil.which(path) or path
    if not Path(path).is_file():
        raise FileNotFoundError("FFmpeg unavailable; run bootstrap or set TRAILER_STUDIO_FFMPEG")
    return str(Path(path).resolve())


def run(arguments: list[str], log: Path | None = None, timeout=600):
    result = subprocess.run(
        [str(x) for x in arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(arguments) + "\n" + result.stdout + result.stderr + "\n")
    if result.returncode:
        raise RuntimeError(f"{Path(arguments[0]).name} exited {result.returncode}:\n{result.stderr[-5000:]}")
    return result


def probe(path: Path) -> dict:
    with av.open(str(path)) as container:
        streams = []
        for stream in container.streams:
            c = stream.codec_context
            item = dict(
                type=stream.type,
                codec=c.name,
                duration=float(stream.duration * stream.time_base) if stream.duration else None,
            )
            if stream.type == "video":
                item.update(
                    width=c.width,
                    height=c.height,
                    frames=stream.frames,
                    fps=float(stream.average_rate) if stream.average_rate else None,
                )
            elif stream.type == "audio":
                item.update(sample_rate=c.sample_rate, channels=c.channels)
            streams.append(item)
        return dict(
            path=str(path),
            duration=container.duration / av.time_base if container.duration else 0,
            streams=streams,
        )


def doctor() -> dict:
    path = ffmpeg()
    encoders = run([path, "-hide_banner", "-encoders"]).stdout
    filters = run([path, "-hide_banner", "-filters"]).stdout
    result = dict(
        ffmpeg=path,
        ffmpeg_version=run([path, "-version"]).stdout.splitlines()[0],
        pyav=av.__version__,
        libx264="libx264" in encoders,
        nvenc_compiled="h264_nvenc" in encoders,
        subtitles="subtitles" in filters,
        rubberband="rubberband" in filters,
        ffprobe=shutil.which("ffprobe"),
    )
    result["passed"] = result["libx264"]
    # A compiled NVENC encoder is not proof of an installed compatible GPU/driver.
    return result


def verify(
    path: Path,
    expected_duration: float | None = None,
    fps: int | None = None,
    width: int | None = None,
    height: int | None = None,
    require_audio=True,
) -> dict:
    info = probe(path)
    videos = [s for s in info["streams"] if s["type"] == "video"]
    audio = [s for s in info["streams"] if s["type"] == "audio"]
    errors = []
    if len(videos) != 1:
        errors.append("Expected exactly one video stream")
    frames = 0
    times = []
    if videos:
        v = videos[0]
        for key, expected in [("width", width), ("height", height), ("fps", fps)]:
            if expected and (v[key] is None or abs(v[key] - expected) > 0.001):
                errors.append(f"{key}: {v[key]} != {expected}")
        with av.open(str(path)) as container:
            for frame in container.decode(video=0):
                frames += 1
                if frame.time is not None:
                    times.append(float(frame.time))
        if fps and len(times) > 1 and max(abs(b - a - 1 / fps) for a, b in zip(times, times[1:])) > 0.0001:
            errors.append("Video timestamps do not have the requested constant cadence")
        if expected_duration is not None:
            if abs(info["duration"] - expected_duration) > max(0.06, 1 / (fps or 30)):
                errors.append("Container duration differs from the requested duration")
            if fps and frames != round(expected_duration * fps):
                errors.append("Decoded frame count differs from the requested duration")
    if require_audio and not audio:
        errors.append("Missing audio stream")
    audio_samples = 0
    if audio:
        with av.open(str(path)) as container:
            for frame in container.decode(audio=0):
                audio_samples += frame.samples
        if not audio_samples:
            errors.append("Audio decoded no samples")
    # Decode all streams once more through the actual production FFmpeg binary.
    run([ffmpeg(), "-v", "error", "-i", str(path), "-f", "null", "-"], timeout=1800)
    return dict(passed=not errors, errors=errors, frames=frames, audio_samples=audio_samples, media=info)
