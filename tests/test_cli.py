import subprocess
import sys


def test_installed_cli_and_skill_are_usable(tmp_path):
    help_text = subprocess.run(
        [sys.executable, "-m", "trailer_studio", "--help"], capture_output=True, text=True, check=True
    ).stdout
    assert "import-take" in help_text and "ue" in help_text
    subprocess.run(
        [sys.executable, "-m", "trailer_studio", "install-skill", "--destination", str(tmp_path / "skills")],
        check=True,
        capture_output=True,
    )
    skill = tmp_path / "skills/game-trailer-production/SKILL.md"
    assert skill.is_file() and "description:" in skill.read_text(encoding="utf-8")
