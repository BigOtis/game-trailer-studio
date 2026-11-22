# Testing

Run `uv sync --extra dev --frozen`, `uv run pytest`, `uv run ruff check src tests` and
`uv run ruff format --check src tests`.

The normal test suite creates synthetic media through the managed FFmpeg binary, renders/decodes
it, checks exact duration/cadence, audible samples, source-byte cache invalidation, damaged-cache
replacement, captions/music/crop, invalid ranges, path boundaries and bridge process identity.
It never needs your game, saves, GPU inference server or credentials.

`scripts/verify_ue5.py` is an opt-in integration check for a machine with licensed Unreal Engine
and build tools. Its output directory must not already exist. The generated source fixture lives
there alongside a separate trailer workspace. The script stops only its owned launched game PID
in `finally`. Failed recordings and build logs remain available. Actual captured frames/audio and
rendered camera/physics observations are required evidence; a successful compile alone is not a
rendered capture pass.

Public hosted CI tests Python/media on Windows and Linux. It does not download Unreal Engine or
claim to validate native UE on those runners. The UE workflow is manually dispatched to a trusted
self-hosted Windows runner labelled `ue5` with an installed licensed engine. Do not enable that
workflow for arbitrary untrusted pull requests on a personal runner.

For a supported-version claim, record the exact engine build, host platform, native build result,
capture metadata, actual decoded picture/audio and the rendered integration result. Earlier APIs
may compile through guards; that is not a test result. Keep the README compatibility statement in
sync with actual evidence.
