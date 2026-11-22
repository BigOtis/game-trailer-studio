# UE local file protocol v1

Launch opt-in flags: `-TrailerStudio -TrailerSession=<id> -TrailerBridgeDir=<absolute directory>`
`-TrailerOutput=<absolute takes root> -TrailerFFmpeg=<executable> -TrailerFPS=30 -TrailerCodec=libx264`.
The CLI supplies these and an isolated `-UserDir`. `-TrailerDemo` additionally enables the sample world
and test-tone command. It is not used for ordinary game projects.

`state.json` is atomically published at up to 20 Hz:

```json
{"version":1,"session":"id","pid":1234,"ready":true,"map":"MapName",
 "camera":{"active":true,"moving":false,"location":{"x":0,"y":0,"z":160}},
 "recording":{"active":false},"subjects":{},"project":{}}
```

The client writes a UUID-named temporary file, then atomically publishes `inbox/<uuid>.json`:

```json
{"version":1,"id":"32-hex-uuid","session":"id","expected_pid":1234,
 "command":"camera_move","arguments":{"location":{"x":0,"y":100,"z":160},"duration":3}}
```

The game processes commands serially, removes the inbox item and publishes `outbox/<uuid>.json`:

```json
{"id":"32-hex-uuid","ok":true,"error":"","result":{}}
```

Commands: `ping`, `mark`, `capture_start`, `capture_stop`, `camera_set`, `camera_move`,
`camera_restore`, `actor_set`, `subjects_refresh`, `key`, `type_text`, `project`, and fixture-only
`demo_tone`, plus `shutdown` for the opted-in session. See `docs/ue5.md` for their semantics. `capture_start.arguments.take` is a fresh ID.
`project.arguments` is `{"name":"game_handler_name","payload":{}}`.

Acknowledgements report dispatch/start, not asynchronous completion. Observe published state.
A timed-out command is not automatically retried because it may already have executed.
The Python client checks process/session/protocol identity before every command and state read.
The native receiver rejects mismatches. This is local tooling, not a network/API service.

Use one client/recipe runner per session. Do not edit files in a live human game's profile. Access
to the bridge directory implies local control of the explicitly opted-in capture session.
