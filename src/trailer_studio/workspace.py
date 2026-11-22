from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .models import Project, Take, identifier, inside


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def find_workspace(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for root in [start, *start.parents]:
        if (root / "trailer.json").is_file():
            return root
    raise ValueError("No trailer.json found; run trailer-studio init <directory> first")


def project(root: Path) -> Project:
    return Project.model_validate(read_json(root / "trailer.json"))


def initialize(root: Path, name="My Game", width=1920, height=1080, fps=30):
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("Choose an empty trailer workspace")
    root.mkdir(parents=True, exist_ok=True)
    for folder in ["takes", "edits", "recipes", "assets", "review", "exports"]:
        (root / folder).mkdir(exist_ok=True)
    config = Project(name=name, width=width, height=height, fps=fps)
    write_json(root / "trailer.json", config.model_dump())
    (root / "brief.md").write_text(
        f"# {name} trailer\n\nAudience: \nDesired duration: \nTone: \n"
        "Must show: \nMusic / title assets: \nKeep / avoid: \n\n"
        "Direction stays with the developer. Preserve original takes and review every outcome.\n",
        encoding="utf-8",
    )
    write_json(
        root / "edits/main.json",
        {
            "version": 1,
            "name": "First cut",
            "shots": [
                {
                    "kind": "card",
                    "title": name,
                    "subtitle": "Add real gameplay takes to this edit",
                    "duration": 3,
                }
            ],
        },
    )
    return root


def load_take(root: Path, name: str) -> Take:
    identifier(name)
    take = Take.model_validate(read_json(root / "takes" / name / "take.json"))
    if take.id != name:
        raise ValueError("Take ID does not match its directory")
    inside(root, take.video)
    if take.audio:
        inside(root, take.audio)
    return take


def import_take(
    root: Path,
    name: str,
    video: Path,
    audio: Path | None = None,
    provenance="gameplay",
    notes="",
    audio_offset=0,
    build="",
) -> Take:
    identifier(name)
    video = video.resolve()
    if not video.is_file() or (audio and not audio.is_file()):
        raise FileNotFoundError("Source video/audio does not exist")
    dest = root / "takes" / name
    dest.mkdir(parents=True, exist_ok=False)
    source_video = dest / ("video" + video.suffix.lower())
    shutil.copy2(video, source_video)
    source_audio = None
    if audio:
        source_audio = dest / ("audio" + audio.suffix.lower())
        shutil.copy2(audio, source_audio)
    take = Take(
        id=name,
        video=source_video.relative_to(root).as_posix(),
        audio=source_audio.relative_to(root).as_posix() if source_audio else None,
        audio_offset=audio_offset,
        provenance=provenance,
        notes=notes,
        build=build,
    )
    write_json(dest / "take.json", take.model_dump())
    write_json(
        dest / "source-hashes.json",
        {
            "video": sha256(source_video),
            "audio": sha256(source_audio) if source_audio else None,
        },
    )
    return take
