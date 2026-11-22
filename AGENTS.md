# Working on Game Trailer Studio

Keep capture, original takes and edit decisions separate. Never invent gameplay outcomes or silently
replace a take. Use new take IDs and versioned exports. Keep human direction and review central.

Run `uv run pytest` and the synthetic media demonstration after renderer changes. Validate actual
decoded frames, audio and cache invalidation, rather than only checking command construction.
UE integration checks require a locally installed licensed engine and a separate fixture project.
Never attach a test to a human gameplay session or their save directory. Do not package engine
binaries, game assets, local credentials, footage, generated projects or build output in this repo.

The Python CLI and native UE plugin share a versioned file protocol. Keep its commands and examples
aligned. Game-specific interactions use explicit project hooks; avoid arbitrary console execution.
Keep native automation opt-in and excluded from Shipping/Test targets. Never imply engine-version
or platform testing that has not actually run.
