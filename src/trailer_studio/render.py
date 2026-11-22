from __future__ import annotations

import hashlib
import html
import json
import math
import os
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL import __version__ as pillow_version

from . import __version__
from .media import ffmpeg, probe, run, verify
from .models import Edit, Shot, inside
from .workspace import load_take, project, read_json, sha256, write_json


def filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def concat_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "'\\''")


def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def write_captions(edit: Edit, path: Path):
    text = "\n\n".join(
        f"{i + 1}\n{srt_time(c.start)} --> {srt_time(c.end)}\n{c.text}"
        for i, c in enumerate(sorted(edit.captions, key=lambda c: c.start))
    )
    path.write_text(text + "\n", encoding="utf-8")


def card(config, shot: Shot, path: Path):
    image = Image.new("RGB", (config.width, config.height), config.background)
    draw = ImageDraw.Draw(image)
    margin = config.width // 12
    draw.rectangle(
        (margin, config.height * 0.30, config.width - margin, config.height * 0.305), fill=config.accent
    )
    for text, size, at in [(shot.title, config.width // 20, 0.39), (shot.subtitle, config.width // 40, 0.58)]:
        font = ImageFont.load_default(size=max(12, size))
        # Fit each card line to the available canvas; don't silently crop a long title.
        while draw.textbbox((0, 0), text, font=font)[2] > config.width - 2 * margin and size > 10:
            size -= 1
            font = ImageFont.load_default(size=size)
        draw.text((margin, config.height * at), text, font=font, fill=config.foreground)
    image.save(path)


def video_options(config) -> list[str]:
    if config.codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(config.crf)]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(config.crf), "-threads", "2"]


def segment(root: Path, config, shot: Shot, hashes: dict, log: Path):
    assets = {}
    take = None
    if shot.kind == "take":
        take = load_take(root, shot.take)
        if not take.accepted:
            raise ValueError(f"Take {take.id} is rejected; review it before accepting/selecting it")
        video = inside(root, take.video)
        audio = inside(root, take.audio) if take.audio else video
        for name, path in [("video", video), ("audio", audio)]:
            if path not in hashes:
                hashes[path] = sha256(path)
            assets[name] = hashes[path]
        info = probe(video)
        if shot.source_in + shot.duration > info["duration"] + 0.04:
            raise ValueError(f"Selected range exceeds {take.id}'s video duration")
        v = next(s for s in info["streams"] if s["type"] == "video")
        if shot.crop:
            x, y, w, h = shot.crop
            if x + w > v["width"] or y + h > v["height"]:
                raise ValueError(f"Crop exceeds {take.id}'s picture")
        audio_info = probe(audio)
        audio_exists = any(s["type"] == "audio" for s in audio_info["streams"])
        if take.audio and not audio_exists:
            raise ValueError(f"{take.audio} has no audio stream")
        if (
            audio_exists
            and shot.source_in + take.audio_offset + shot.duration > audio_info["duration"] + 0.06
        ):
            raise ValueError(f"Selected range exceeds {take.id}'s audio duration")
    elif shot.image:
        image_path = inside(root, shot.image)
        hashes.setdefault(image_path, sha256(image_path))
        assets["image"] = hashes[image_path]
    signature = dict(
        shot=shot.model_dump(),
        take=take.model_dump() if take else None,
        assets=assets,
        config=config.model_dump(),
        version=__version__,
        renderer=sha256(Path(__file__)),
        pillow=pillow_version,
        ffmpeg=run([ffmpeg(), "-version"]).stdout.splitlines()[0],
    )
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    cache = root / ".trailer-studio/cache" / key
    cache.mkdir(parents=True, exist_ok=True)
    picture, sound = cache / "video.mp4", cache / "audio.wav"
    receipt = cache / "segment.json"
    if receipt.exists() and picture.exists() and sound.exists():
        prior = read_json(receipt)
        if prior.get("video_sha256") == sha256(picture) and prior.get("audio_sha256") == sha256(sound):
            return picture, sound, key, True
    count = round(shot.duration * config.fps)
    duration = count / config.fps
    args = [ffmpeg(), "-v", "error", "-y"]
    if take:
        args += ["-ss", str(shot.source_in), "-i", str(video)]
    elif shot.kind == "static":
        args += ["-f", "lavfi", "-i", f"color=c=0x172127:s={config.width}x{config.height}:r={config.fps}"]
    else:
        image_path = inside(root, shot.image) if shot.image else cache / "card.png"
        if not shot.image:
            card(config, shot, image_path)
        args += ["-loop", "1", "-framerate", str(config.fps), "-i", str(image_path)]
    filters = []
    if shot.crop:
        filters.append("crop=" + ":".join(str(v) for v in shot.crop[2:] + shot.crop[:2]))
    w, h = config.width, config.height
    if shot.fit == "cover":
        filters += [f"scale={w}:{h}:force_original_aspect_ratio=increase", f"crop={w}:{h}"]
    else:
        filters += [
            f"scale={w}:{h}:force_original_aspect_ratio=decrease",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
        ]
    if shot.kind == "static":
        filters.append("noise=alls=85:allf=t,format=gray")
    filters += ["setsar=1", f"fps={config.fps}", "format=yuv420p"]
    run(
        args
        + [
            "-vf",
            ",".join(filters),
            "-an",
            "-frames:v",
            str(count),
            *video_options(config),
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-movflags",
            "+faststart",
            str(picture),
        ],
        log,
    )
    args = [ffmpeg(), "-v", "error", "-y"]
    af = f"aresample={config.sample_rate},aformat=channel_layouts=stereo"
    if take and audio_exists:
        start = shot.source_in + take.audio_offset
        args += ["-ss", str(max(0, start)), "-i", str(audio)]
        if start < 0:
            af += f",adelay={round(-start * 1000)}:all=1"
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    if shot.pitch_semitones:
        af += f",rubberband=pitch={2 ** (shot.pitch_semitones / 12):.9f}:formant=preserved"
    af += f",volume={shot.audio_gain},apad,atrim=duration={duration},asetpts=PTS-STARTPTS"
    run(
        args
        + [
            "-vn",
            "-af",
            af,
            "-t",
            str(duration),
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(sound),
        ],
        log,
    )
    write_json(receipt, dict(signature=signature, video_sha256=sha256(picture), audio_sha256=sha256(sound)))
    return picture, sound, key, False


def envelope(points):
    if not points:
        return "1"
    result = str(points[-1][1])
    for (at, gain), (end, end_gain) in reversed(list(zip(points, points[1:]))):
        slope = (end_gain - gain) / (end - at)
        result = f"if(lt(t,{end}),{gain}+({slope})*(t-{at}),{result})"
    return f"if(lt(t,{points[0][0]}),{points[0][1]},{result})"


def render(root: Path, edit_path: Path, output: Path):
    config = project(root)
    edit = Edit.model_validate(read_json(edit_path))
    duration = edit.validate_timeline(config.fps)
    output = inside(root, output)
    if output.exists():
        raise FileExistsError("Choose a new versioned export filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = root / ".trailer-studio/renders" / uuid.uuid4().hex
    work.mkdir(parents=True)
    log = work / "ffmpeg.log"
    hashes, parts = {}, []
    for shot in edit.shots:
        parts.append(segment(root, config, shot, hashes, log))
    for kind, index in [("video", 0), ("audio", 1)]:
        (work / (kind + ".ffconcat")).write_text(
            "ffconcat version 1.0\n" + "".join(f"file '{concat_path(part[index])}'\n" for part in parts),
            encoding="utf-8",
        )
    captions = work / "captions.srt"
    write_captions(edit, captions)
    args = [
        ffmpeg(),
        "-v",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(work / "video.ffconcat"),
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(work / "audio.ffconcat"),
    ]
    audio_filter = "[1:a]apad,atrim=duration=" + str(duration) + "[mix]"
    if edit.music:
        music = inside(root, edit.music.path)
        hashes[music] = sha256(music)
        args += ["-stream_loop", "-1", "-ss", str(edit.music.offset), "-i", str(music)]
        expression = envelope(edit.music.envelope)
        audio_filter = (
            f"[2:a]aresample=48000,volume='{expression}':eval=frame,volume={edit.music.gain},"
            f"atrim=duration={duration}[score];[1:a][score]amix=inputs=2:normalize=0,"
            f"apad,atrim=duration={duration}[mix]"
        )
    audio_filter += ";[mix]alimiter=limit=0.89:level=false:latency=1[finalaudio]"
    args += ["-filter_complex", audio_filter, "-map", "0:v:0", "-map", "[finalaudio]"]
    if edit.burn_captions and edit.captions:
        args += ["-vf", f"subtitles='{filter_path(captions)}'", *video_options(config)]
    else:
        args += ["-c:v", "copy"]
    temporary = work / "export.mp4"
    run(
        args
        + [
            "-frames:v",
            str(round(duration * config.fps)),
            "-t",
            str(duration),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        log,
    )
    check = verify(temporary, duration, config.fps, config.width, config.height)
    write_json(work / "verification.json", check)
    if not check["passed"]:
        raise ValueError(f"Export failed verification: {check['errors']}; see {work}")
    temporary.replace(output)
    output.with_suffix(".srt").write_text(captions.read_text(encoding="utf-8"), encoding="utf-8")
    receipt = dict(
        version=1,
        passed=True,
        output=output.relative_to(root).as_posix(),
        edit=edit_path.resolve().relative_to(root).as_posix(),
        duration=duration,
        output_sha256=sha256(output),
        edit_sha256=sha256(edit_path),
        sources={p.relative_to(root).as_posix(): value for p, value in hashes.items()},
        segments=[dict(key=p[2], cached=p[3]) for p in parts],
        verification=check,
        work=work.relative_to(root).as_posix(),
        note="CFR output may repeat real rendered frames; metadata is not proof of unique game FPS.",
    )
    write_json(output.with_suffix(".render.json"), receipt)
    return receipt


def review(root: Path, edit_path: Path, video: Path, output: Path):
    import av

    config = project(root)
    edit = Edit.model_validate(read_json(edit_path))
    output = inside(root, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    video = inside(root, video)
    images = output.parent / (output.stem + "-frames")
    images.mkdir(exist_ok=True)
    times, at = [], 0.0
    for shot in edit.shots:
        times.append(at + min(0.5, shot.duration / 2))
        at += shot.duration
    thumbnails = []
    with av.open(str(video)) as container:
        for i, at in enumerate(times):
            container.seek(int(at * av.time_base), backward=True)
            for frame in container.decode(video=0):
                if frame.time is None or frame.time >= at - 0.02:
                    image = frame.to_image()
                    image.thumbnail((320, 180))
                    image.save(images / f"{i:03}.jpg", quality=88)
                    thumbnails.append(image)
                    break
    sheet = Image.new("RGB", (960, 208 * math.ceil(len(thumbnails) / 3)), config.background)
    draw = ImageDraw.Draw(sheet)
    for i, image in enumerate(thumbnails):
        x, y = i % 3 * 320, i // 3 * 208
        sheet.paste(image, (x, y))
        draw.text(
            (x + 8, y + 184), f"{times[i]:.2f}s  {edit.shots[i].take or edit.shots[i].kind}", fill="white"
        )
    contact = output.with_suffix(".contact.jpg")
    sheet.save(contact, quality=90)

    def relative(path):
        return Path(os.path.relpath(path, output.parent)).as_posix()

    from urllib.parse import quote

    chapters, at = [], 0.0
    for i, shot in enumerate(edit.shots):
        chapters.append(
            f'<button data-time="{at:.6f}">{i + 1:02} / {html.escape(shot.purpose or shot.take or shot.kind)}</button>'
        )
        at += shot.duration
    source = html.escape(quote(relative(video)), quote=True)
    track = html.escape(quote(relative(video.with_suffix(".srt"))), quote=True)
    # SRT is delivered for editors; browsers need WebVTT tracks.
    vtt = output.with_suffix(".vtt")
    vtt.write_text(
        "WEBVTT\n\n"
        + "\n\n".join(
            f"{srt_time(c.start).replace(',', '.')} --> {srt_time(c.end).replace(',', '.')}\n{c.text}"
            for c in edit.captions
        )
        + "\n",
        encoding="utf-8",
    )
    track = html.escape(quote(relative(vtt)), quote=True)
    text = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(edit.name)}</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#eef0ed;color:#172127;font:16px/1.6 system-ui}}main{{max-width:1200px;margin:auto;padding:28px}}video,img{{width:100%;display:block}}nav{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}}button{{background:#fff;border:1px solid #346573;padding:10px;cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style><main><p>GAME TRAILER STUDIO / REVIEW</p><h1>{html.escape(edit.name)}</h1><video controls preload="metadata" src="{source}"><track kind="captions" src="{track}" srclang="en" label="Captions"></video><nav>{"".join(chapters)}</nav><h2>Contact sheet</h2><img src="{html.escape(quote(relative(contact)), quote=True)}" alt="Shot contact sheet"><h2>Directing notes</h2><p>Review the request, result, motion, speech and pacing. Keep earlier versions.</p><details><summary>Edit manifest</summary><pre>{html.escape(json.dumps(edit.model_dump(), indent=2))}</pre></details></main><script>const v=document.querySelector('video');document.querySelectorAll('[data-time]').forEach(b=>b.onclick=()=>{{v.currentTime=+b.dataset.time;v.play().catch(()=>{{}})}});</script></html>'''
    output.write_text(text, encoding="utf-8")
    return dict(review=str(output), contact_sheet=str(contact))
