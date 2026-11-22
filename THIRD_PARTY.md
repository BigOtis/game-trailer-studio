# Dependency and asset notes

- This repository contains original toolkit source under the MIT license in `LICENSE`.
- [Unreal Engine](https://www.unrealengine.com/) is separately obtained/licensed from Epic. This
  repository references public engine APIs and basic shapes in a runtime fixture; it does not
  distribute Epic source, binaries or content.
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) provides a platform-specific FFmpeg
  executable through its installed wheel. The wrapper and executable have their respective license
  terms. FFmpeg builds vary in enabled components/licenses; inspect your installed build with
  `ffmpeg -version` / `-buildconf` and the distributor's notices before redistributing binaries.
- [PyAV](https://github.com/PyAV-Org/PyAV), [Pillow](https://python-pillow.github.io/),
  [Pydantic](https://docs.pydantic.dev/), pytest and Ruff retain their own licenses. Dependency
  packages/binaries are fetched during installation, not vendored into this repository.
- No footage, game art, recorded dialogue, music, marketplace assets, model weights or credentials
  from the original production are included. Demo patterns, simple title cards and a fixture test
  tone are generated locally for clearly labelled technical tests.
- Optional HTML motion graphics tools such as [HyperFrames](https://github.com/heygen-com/hyperframes)
  can render clips for importing as editorial takes; they are not required dependencies of this release.
