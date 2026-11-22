"""Regenerate editor/tool schemas from the same models used by the CLI."""

from pathlib import Path

from trailer_studio.models import Edit, Project, Recipe, Take
from trailer_studio.workspace import write_json

root = Path(__file__).resolve().parents[1] / "schemas"
for name, model in [("project", Project), ("take", Take), ("edit", Edit), ("recipe", Recipe)]:
    write_json(root / (name + ".schema.json"), model.model_json_schema())
print(root)
