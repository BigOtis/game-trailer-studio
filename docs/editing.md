# Editing, audio and re-capture

`trailer.json` sets output name, even width/height, integer fps, codec/quality and title-card colors.
Paths within edit/take manifests are relative to the trailer workspace and are checked against
traversal. Import media from elsewhere with `import-take`; the source is copied under a new take ID.

## Take metadata

`takes/<id>/take.json` identifies `video`, optional separate `audio`, `audio_offset`, `build`,
`provenance` (`gameplay`, `editorial`, `synthetic-test`), `accepted` and `notes`.
Keep the capture/event logs beside it. Rejected takes are retained; the renderer refuses to select
them until you explicitly accept them with `take-status <id> --accepted yes --notes ...`.
Technical success is separate from editorial acceptance. Review real motion/contact/outcomes.

## Edit fields

Each shot has `duration` and optional `purpose`:

- `kind: take` (default): `take`, `source_in`, optional `crop: [x,y,width,height]`,
  `fit: contain|cover`, `audio_gain`, `pitch_semitones`.
- `kind: card`: `title`, `subtitle`, or `image` pointing at your own artwork.
- `kind: static`: an explicitly editorial noise transition.

Durations must align to the output frame grid. Set `expected_duration` to enforce the exact cut
length. Media source ranges and crops are validated before rendering. A whole action needs room
for request, response, contact/result and reaction; an empty action queue is not evidence of a
completed physics outcome.

Captions are `{"start":2,"end":4,"text":"Actual recorded words"}` entries on the final timeline.
SRT is always delivered, and review HTML uses WebVTT. `burn_captions: true` additionally uses FFmpeg's
subtitles/libass filter; `doctor` reports availability. Text/timing must come from the selected take.
There is no ASR alignment in this first release. Estimated timings need review.

## Music and sound

```json
{"music":{"path":"assets/your-licensed-score.wav","offset":20,"gain":0.15,
          "envelope":[[0,0.1],[3,0.8],[8,0.1],[58,0.8],[60,0]]}}
```

Points are increasing timeline seconds and linearly interpolated gain multipliers. This example is
for a sixty-second edit; adapt its duration and source offset. Music loops when necessary. The final
mix has a peak limiter, not an automatic integrated-loudness target. Measure the delivery against
your platform's actual requirements; do not infer a LUFS result from the limiter setting.

`pitch_semitones` uses duration-preserving Rubber Band processing, when compiled into your FFmpeg.
It affects the selected audio interval. A captured master mix includes effects/voices together;
an imported separate voice stem is a different source. Do not call a mix an isolated dialogue stem.

## Refresh a cut

Record a recipe using a fresh take name, review the new source, then:

```sh
trailer-studio --workspace /trailers/my-game retarget edits/main.json old_take new_take --output edits/main-v2.json
```

`retarget` changes references and optionally accepts one explicit `--source-in`. It intentionally
does not guess dialogue timing. When several slices of a take are selected, review each source
range individually in the new edit. Render refuses selections outside the new recording.

Rendering uses source content hashes, treatment, take metadata, project settings, renderer source,
FFmpeg version and Pillow version in its cache key. Cached output hashes are checked too. New take
IDs and new export filenames preserve provenance; caches are conveniences, not authoritative source.

Exports are finalized only after actual frame/audio/full-decode checks pass. Each `.render.json`
records sources, hashes, segment cache keys and verification. Always watch the resulting film and
listen to its mix. A passing validator says nothing about the clarity of the promise you are making
to your players.
