from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ValueError("Use 1–80 letters, digits, underscores or hyphens; start with a letter/digit.")
    return value


def inside(root: Path, value: str | Path) -> Path:
    root = root.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path leaves the trailer workspace: {value}")
    return path


class Project(Model):
    version: Literal[1] = 1
    name: str = "My Game"
    width: int = Field(default=1920, ge=128, le=7680, multiple_of=2)
    height: int = Field(default=1080, ge=128, le=4320, multiple_of=2)
    fps: int = Field(default=30, ge=1, le=120)
    codec: Literal["libx264", "h264_nvenc"] = "libx264"
    crf: int = Field(default=18, ge=0, le=40)
    sample_rate: Literal[48000] = 48000
    background: str = "#172127"
    foreground: str = "#f2f0e7"
    accent: str = "#58a6b8"


class Take(Model):
    version: Literal[1] = 1
    id: str
    video: str
    audio: str | None = None
    audio_offset: float = 0
    provenance: Literal["gameplay", "editorial", "synthetic-test"] = "gameplay"
    accepted: bool = True
    notes: str = ""
    build: str = ""

    @model_validator(mode="after")
    def valid_id(self):
        identifier(self.id)
        if not math.isfinite(self.audio_offset):
            raise ValueError("audio_offset must be finite")
        return self


class Shot(Model):
    kind: Literal["take", "card", "static"] = "take"
    take: str | None = None
    source_in: float = Field(default=0, ge=0, allow_inf_nan=False)
    duration: float = Field(gt=0, le=3600, allow_inf_nan=False)
    purpose: str = ""
    crop: tuple[int, int, int, int] | None = None
    fit: Literal["contain", "cover"] = "contain"
    title: str = ""
    subtitle: str = ""
    image: str | None = None
    audio_gain: float = Field(default=1, ge=0, le=4, allow_inf_nan=False)
    pitch_semitones: float = Field(default=0, ge=-12, le=12, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_shot(self):
        if self.kind == "take":
            if not self.take:
                raise ValueError("A take shot needs a take ID")
            identifier(self.take)
        elif self.take:
            raise ValueError("Only take shots may reference takes")
        if self.crop and (min(self.crop[:2]) < 0 or min(self.crop[2:]) <= 0):
            raise ValueError("crop is [x>=0, y>=0, width>0, height>0]")
        return self


class Caption(Model):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    text: str

    @model_validator(mode="after")
    def valid_range(self):
        if self.end <= self.start:
            raise ValueError("Caption end must follow start")
        return self


class Music(Model):
    path: str
    offset: float = Field(default=0, ge=0, allow_inf_nan=False)
    gain: float = Field(default=0.12, ge=0, le=2, allow_inf_nan=False)
    # [timeline seconds, linear gain], interpolated by FFmpeg expressions.
    envelope: list[tuple[float, float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered(self):
        last = -1.0
        for at, gain in self.envelope:
            if not math.isfinite(at + gain) or at < 0 or gain < 0 or at <= last:
                raise ValueError("Music points need finite, increasing times and nonnegative gains")
            last = at
        return self


class Edit(Model):
    version: Literal[1] = 1
    name: str
    shots: list[Shot] = Field(min_length=1, max_length=200)
    expected_duration: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    music: Music | None = None
    captions: list[Caption] = Field(default_factory=list)
    burn_captions: bool = False

    def duration(self, fps: int) -> float:
        return sum(round(s.duration * fps) for s in self.shots) / fps

    def validate_timeline(self, fps: int):
        for shot in self.shots:
            if round(shot.duration * fps) < 1:
                raise ValueError("Every shot must occupy at least one output frame")
            if abs(shot.duration * fps - round(shot.duration * fps)) > 0.001:
                raise ValueError(f"Shot duration {shot.duration} is not aligned to {fps} fps")
        duration = self.duration(fps)
        if self.expected_duration is not None and abs(duration - self.expected_duration) > 0.0001:
            raise ValueError(f"Timeline is {duration}s; expected {self.expected_duration}s")
        for caption in self.captions:
            if caption.end > duration + 0.001:
                raise ValueError("Caption extends beyond the edit")
        return duration


class Command(Model):
    command: str
    arguments: dict = Field(default_factory=dict)


class Wait(Model):
    path: str
    equals: object = True
    timeout: float = Field(default=60, gt=0, le=3600)


class Step(Model):
    command: str | None = None
    arguments: dict = Field(default_factory=dict)
    wait: Wait | None = None
    hold: float | None = Field(default=None, ge=0, le=3600)
    mark: str | None = None

    @model_validator(mode="after")
    def one_operation(self):
        if sum(v is not None for v in [self.command, self.wait, self.hold, self.mark]) != 1:
            raise ValueError("A recipe step needs exactly one command, wait, hold or mark")
        return self


class Recipe(Model):
    version: Literal[1] = 1
    name: str
    purpose: str = ""
    setup: list[Step] = Field(default_factory=list)
    record: list[Step] = Field(default_factory=list)
    build: str = ""
