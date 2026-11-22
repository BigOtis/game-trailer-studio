from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, media, render, unreal
from . import demo as demos
from .models import Edit, inside
from .workspace import find_workspace, import_take, initialize, load_take, read_json, write_json


def parser():
    p = argparse.ArgumentParser(description="Real gameplay, editable cuts, repeatable capture.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--workspace", type=Path, help="Trailer workspace; otherwise discover trailer.json upward")
    sub = p.add_subparsers(dest="task", required=True)
    init = sub.add_parser("init")
    init.add_argument("directory", type=Path)
    init.add_argument("--name", default="My Game")
    init.add_argument("--width", type=int, default=1920)
    init.add_argument("--height", type=int, default=1080)
    init.add_argument("--fps", type=int, default=30)
    sub.add_parser("doctor")
    sub.add_parser("demo")
    take = sub.add_parser("import-take")
    take.add_argument("id")
    take.add_argument("--video", type=Path, required=True)
    take.add_argument("--audio", type=Path)
    take.add_argument("--provenance", choices=["gameplay", "editorial", "synthetic-test"], default="gameplay")
    take.add_argument("--notes", default="")
    take.add_argument("--build", default="")
    take.add_argument("--audio-offset", type=float, default=0)
    sub.add_parser("takes")
    status = sub.add_parser("take-status")
    status.add_argument("id")
    status.add_argument("--accepted", choices=["yes", "no"], required=True)
    status.add_argument("--notes", default="")
    cut = sub.add_parser("render")
    cut.add_argument("edit", type=Path)
    cut.add_argument("--output", type=Path, required=True)
    rev = sub.add_parser("review")
    rev.add_argument("edit", type=Path)
    rev.add_argument("--video", type=Path, required=True)
    rev.add_argument("--output", type=Path, default=Path("review/index.html"))
    check = sub.add_parser("verify")
    check.add_argument("file", type=Path)
    check.add_argument("--duration", type=float)
    check.add_argument("--fps", type=int)
    ret = sub.add_parser("retarget")
    ret.add_argument("edit", type=Path)
    ret.add_argument("old")
    ret.add_argument("new")
    ret.add_argument("--output", type=Path, required=True)
    ret.add_argument("--source-in", type=float)
    skill = sub.add_parser("install-skill")
    skill.add_argument(
        "--destination", type=Path, required=True, help="Skill parent directory, e.g. .agents/skills"
    )
    ue = sub.add_parser("ue").add_subparsers(dest="ue_task", required=True)
    inst = ue.add_parser("install")
    inst.add_argument("--project", type=Path, required=True)
    fixture = ue.add_parser("fixture")
    fixture.add_argument("--directory", type=Path, required=True)
    fixture.add_argument("--engine", type=Path, required=True)
    build = ue.add_parser("build")
    build.add_argument("--project", type=Path, required=True)
    build.add_argument("--engine", type=Path)
    build.add_argument("--log", type=Path, default=Path("ue-build.log"))
    launch = ue.add_parser("launch")
    launch.add_argument("--project", type=Path, required=True)
    launch.add_argument("--engine", type=Path)
    launch.add_argument("--map", default="/Engine/Maps/Entry")
    launch.add_argument("--demo", action="store_true")
    for name in ["state", "command", "capture", "stop"]:
        item = ue.add_parser(name)
        item.add_argument("--session", type=Path, required=True)
        if name == "command":
            item.add_argument("name")
            item.add_argument("--arguments", default="{}")
        if name == "capture":
            item.add_argument("recipe", type=Path)
            item.add_argument("--take", required=True)
    return p


def execute(a):
    if a.task == "init":
        return {"workspace": str(initialize(a.directory, a.name, a.width, a.height, a.fps))}
    if a.task == "doctor":
        return media.doctor()
    if a.task == "verify":
        return media.verify(a.file.resolve(), a.duration, a.fps)
    if a.task == "install-skill":
        dest = a.destination.resolve() / "game-trailer-production"
        if dest.exists():
            raise FileExistsError("Skill already exists; preserve or replace it explicitly")
        shutil.copytree(unreal.bundled("game-trailer-production"), dest)
        return {"skill": str(dest)}
    if a.task == "ue":
        if a.ue_task == "install":
            return unreal.install_plugin(a.project)
        if a.ue_task == "fixture":
            return {"project": str(unreal.fixture(a.directory, a.engine.resolve()))}
        if a.ue_task == "build":
            return unreal.build(a.project, unreal.resolve_engine(a.project, a.engine), a.log.resolve())
        if a.ue_task == "state":
            return unreal.Bridge(a.session).state()
        if a.ue_task == "stop":
            return unreal.stop_session(a.session)
        if a.ue_task == "command":
            return unreal.Bridge(a.session).command(a.name, json.loads(a.arguments))
    root = find_workspace(a.workspace)
    if a.task == "demo":
        return demos.demo(root)
    if a.task == "import-take":
        return import_take(
            root, a.id, a.video, a.audio, a.provenance, a.notes, a.audio_offset, a.build
        ).model_dump()
    if a.task == "takes":
        return [
            load_take(root, p.parent.name).model_dump() for p in sorted((root / "takes").glob("*/take.json"))
        ]
    if a.task == "take-status":
        take = load_take(root, a.id)
        take.accepted = a.accepted == "yes"
        take.notes = a.notes or take.notes
        write_json(root / "takes" / a.id / "take.json", take.model_dump())
        return take.model_dump()
    if a.task == "render":
        return render.render(root, inside(root, a.edit), a.output)
    if a.task == "review":
        return render.review(root, inside(root, a.edit), a.video, a.output)
    if a.task == "retarget":
        load_take(root, a.new)
        edit = Edit.model_validate(read_json(inside(root, a.edit)))
        changed = 0
        for shot in edit.shots:
            if shot.take == a.old:
                shot.take = a.new
                changed += 1
                if a.source_in is not None:
                    shot.source_in = a.source_in
        if not changed:
            raise ValueError("The old take was not selected in this edit")
        dest = inside(root, a.output)
        if dest.exists():
            raise FileExistsError("Choose a new edit filename")
        write_json(dest, edit.model_dump())
        return {
            "edit": str(dest),
            "changed": changed,
            "review_required": "Re-select new source ranges and captions before rendering",
        }
    if a.task == "ue" and a.ue_task == "launch":
        manifest = unreal.launch(root, a.project, unreal.resolve_engine(a.project, a.engine), a.map, a.demo)
        return {"session": str(manifest)}
    if a.task == "ue" and a.ue_task == "capture":
        return unreal.capture_recipe(root, inside(root, a.recipe), a.session, a.take)
    raise ValueError("Unknown operation")


def main():
    try:
        value = execute(parser().parse_args())
        print(json.dumps(value, indent=2, ensure_ascii=False))
        if isinstance(value, dict) and value.get("passed") is False:
            raise SystemExit(1)
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
