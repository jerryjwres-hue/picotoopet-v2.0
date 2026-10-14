# C009B Windows Master Mux Hardening v1

Scope: `FixedFfmpegMasterVideoComposer.cs`, `MasterVideoProcessRunner.cs`, `MasterVideoMediaProbe.cs`, the isolated `PicotooPet.PostProductionMasterMux.SmokeTests` harness and the isolated workflow `c009b-windows-master-mux-hardening.yml`.

Frozen and unchanged: ffmpeg arguments, H.264 `-c:v copy`, AAC-LC 48 kHz mono 128k, stereo `pan=mono|c0=0.5*c0+0.5*c1`, zero-narration byte copy, `IMasterVideoComposer`, the C009A contract.

## What changed

| Area | Change |
| --- | --- |
| Paths | `MasterVideoPathPolicy` rejects UNC, `\\?\`, `\\.\`, root-relative, drive-relative, relative, alternate data streams, reserved device names and invalid characters with `MASTER_MUX_PATH_INVALID` before any filesystem I/O. Reparse points on the file and its immediate parent directory are rejected. The media probe applies the same policy. |
| WAV | A single bounded read (32 MiB per file, 256 MiB total, size re-checked against the declared C009A bytes). The strict PCM16 parser mirrors C009A `ParseWav` and adds a chunk-count limit. Failures use closed `MASTER_MUX_*` codes. |
| TOCTOU | The visual and each WAV are opened once with `FileShare.Read`. Hash and parse come from that handle, and the handle stays open through ffprobe and ffmpeg. Other writers, deletes and renames are denied. |
| Cleanup | Kill and drain exceptions cannot replace cancel or timeout semantics. Only `AggregateException`, `NotSupportedException`, `Win32Exception` and `InvalidOperationException` are absorbed. A single-process `Kill()` fallback always runs. Unrelated exceptions propagate. `CleanupIncomplete` reports unconfirmed termination. |

## Documented limits (not eliminated)

- Pre-open race: a symlink or junction swapped on the leaf path between the pre-open reparse check and `CreateFile` is not detectable. Once opened, the handle pins the file.
- Reparse checks cover the file and its immediate parent only. Ancestor directories are C009A's responsibility.
- Unrecoverable cleanup: if the OS refuses to terminate a process (EDR protection, handle inheritance), the runner returns or throws the cancel/timeout result and sets `CleanupIncomplete`. It cannot force termination.
- Job Object containment (follow-up, Issue #73): the runner places each ffmpeg/ffprobe process in a `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` Job Object right after `Process.Start`, then adopts any descendants already present. Termination calls `TerminateJobObject` independently of `Kill(entireProcessTree)`. Residual windows: `Process.Start` has no `CREATE_SUSPENDED`, so a descendant created before the job assignment is only caught by the follow-up descendant sweep (up to 3 passes); if a descendant exited or re-parented before the sweep it is not tracked. If the job cannot be created or assigned (old OS, an outer job forbidding nesting) the runner silently falls back to the earlier tree-kill behavior with no containment guarantee.
- The held-handle guarantee covers files the composer opened. The directory that holds them is not locked.

## Deferred (not required for this task)

Arbitrary executable resolution, long-path support, sub-5 ms timing, 44.1 kHz boundary precision.

## Verification

Local Linux: contract tests only (342 passed). Windows CI run 38022563554 on 30d29411 passed all required markers (earlier runs 1–4 failed on test-side issues fixed in the follow-up commits). Native Windows verification is the GitHub Actions run of `c009b-windows-master-mux-hardening.yml`; the required markers are `MASTER_MUX_UNIT`, `MASTER_MUX_REAL_WINDOWS`, `MASTER_MUX_HARDENING_UNIT` and `MASTER_MUX_HARDENING_REAL`, all `PASS`. Anything not observed there is UNVERIFIED.

## Job Object evidence (Windows CI)

- Attribution, run 38643441946 (`6caea913`): root `ffmpeg.exe` pid 5592 had children `conhost.exe` and `ffmpeg.exe` (pid 976) before the kill. With only the single-process fallback the root exited and pid 976 survived with `ppid=5592`, `descendant_of_root=True`. The leftover belonged to the spawned command, not to unrelated runner activity. The exact reason `ffmpeg.exe` spawns an `ffmpeg.exe` child (launcher shim vs. the build's own behavior) is UNVERIFIED.
- Fix, run 38644278292 (`6eb752ca`): all four forced-failure paths (NotSupported-throwing killer and no-op killer, each on timeout and on cancel) saw 1 `ffmpeg.exe` child before the kill and `owned_live_descendants_after=0` afterwards, with timeout/cancel semantics preserved. The original markers (3 profiles, zero narration, bounded and failure, held handles) stayed `PASS`.
