import array
from pathlib import Path

import av
import pytest

from trailer_studio.demo import demo
from trailer_studio.media import ffmpeg, run, verify
from trailer_studio.render import render, review
from trailer_studio.workspace import initialize, load_take, read_json, write_json


@pytest.fixture
def workspace(tmp_path):
    initialize(tmp_path, "Test Game", width=320, height=180)
    demo(tmp_path)
    return tmp_path


def test_actual_render_frames_audio_captions_and_review(workspace):
    root = workspace
    first = render(root, root / "edits/demo.json", Path("exports/first.mp4"))
    assert first["verification"]["frames"] == 300
    assert first["verification"]["audio_samples"] >= 479000
    resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
    peak = 0
    with av.open(str(root / "exports/first.mp4")) as container:
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                values = array.array("h", bytes(converted.planes[0]))
                peak = max(peak, max(abs(v) for v in values))
    assert peak > 100
    page = review(root, root / "edits/demo.json", Path("exports/first.mp4"), Path("review/index.html"))
    assert Path(page["contact_sheet"]).is_file()
    assert "demo-pattern" in (root / "review/index.html").read_text(encoding="utf-8")
    assert "Synthetic demo" in (root / "exports/first.srt").read_text(encoding="utf-8")
    assert verify(root / "exports/first.mp4", 10, 30)["passed"]
    assert not verify(root / "exports/first.mp4", 9, 30)["passed"]
    with pytest.raises(FileExistsError):
        render(root, root / "edits/demo.json", Path("exports/first.mp4"))


def test_cache_uses_source_bytes_and_detects_corrupted_cached_output(workspace):
    root = workspace
    initial = render(root, root / "edits/demo.json", Path("exports/one.mp4"))
    reused = render(root, root / "edits/demo.json", Path("exports/two.mp4"))
    assert all(p["cached"] for p in reused["segments"])
    source = root / load_take(root, "demo-pattern").video
    # Keep the same take ID/path but actually replace its picture with another valid video.
    run(
        [
            ffmpeg(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=320x180:r=30",
            "-t",
            "5",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ]
    )
    updated = render(root, root / "edits/demo.json", Path("exports/three.mp4"))
    assert updated["segments"][1]["key"] != initial["segments"][1]["key"]
    assert not updated["segments"][1]["cached"]
    assert updated["segments"][2]["cached"]
    key = updated["segments"][2]["key"]
    (root / ".trailer-studio/cache" / key / "video.mp4").write_bytes(b"damaged cached output")
    repaired = render(root, root / "edits/demo.json", Path("exports/four.mp4"))
    assert not repaired["segments"][2]["cached"]
    assert repaired["verification"]["passed"]


def test_rejected_and_out_of_range_takes_do_not_become_exports(workspace):
    root = workspace
    take = load_take(root, "demo-pattern")
    take.accepted = False
    write_json(root / "takes/demo-pattern/take.json", take.model_dump())
    with pytest.raises(ValueError, match="rejected"):
        render(root, root / "edits/demo.json", Path("exports/bad.mp4"))
    take.accepted = True
    write_json(root / "takes/demo-pattern/take.json", take.model_dump())
    edit = read_json(root / "edits/demo.json")
    edit["shots"][1]["source_in"] = 4
    write_json(root / "edits/too-long.json", edit)
    with pytest.raises(ValueError, match="exceeds"):
        render(root, root / "edits/too-long.json", Path("exports/too-long.mp4"))


def test_music_envelope_burned_captions_and_crop(workspace):
    root = workspace
    edit = read_json(root / "edits/demo.json")
    edit["music"] = {
        "path": "takes/demo-grid/audio.wav",
        "gain": 0.1,
        "envelope": [[0, 0.1], [2, 0.3], [10, 0]],
    }
    edit["burn_captions"] = True
    edit["shots"][1]["crop"] = [20, 20, 260, 140]
    write_json(root / "edits/music.json", edit)
    result = render(root, root / "edits/music.json", Path("exports/music.mp4"))
    assert result["verification"]["passed"]
    assert "takes/demo-grid/audio.wav" in result["sources"]
