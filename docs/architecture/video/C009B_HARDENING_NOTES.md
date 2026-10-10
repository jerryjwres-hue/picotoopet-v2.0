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
- The held-handle guarantee covers files the composer opened. The directory that holds them is not locked.

## Deferred (not required for this task)

Job Object containment, arbitrary executable resolution, long-path support, sub-5 ms timing, 44.1 kHz boundary precision.

## Verification

Local Linux: contract tests only. Native Windows verification is the GitHub Actions run of `c009b-windows-master-mux-hardening.yml`; the required markers are `MASTER_MUX_UNIT`, `MASTER_MUX_REAL_WINDOWS`, `MASTER_MUX_HARDENING_UNIT` and `MASTER_MUX_HARDENING_REAL`, all `PASS`. Anything not observed there is UNVERIFIED.
