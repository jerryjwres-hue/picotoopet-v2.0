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
- Job Object containment, fail-closed (Issues #73, #83): ffmpeg/ffprobe are started with `CreateProcessW` and `PROC_THREAD_ATTRIBUTE_JOB_LIST`, so the process is inside a `KILL_ON_JOB_CLOSE` Job Object before it executes its first instruction. Descendants inherit the Job; there is no post-start assignment window and no descendant sweep. Inheritance is limited to the three std handles (`PROC_THREAD_ATTRIBUTE_HANDLE_LIST`). If the Job cannot be created, the system refuses enrollment, enrollment verification (`IsProcessInJob`) fails, or the OS is not Windows, the runner starts nothing (or terminates what it started) and fails with `MASTER_MUX_PROCESS_CONTAINMENT_FAILED`; there is no silent fallback to the earlier behavior. `MasterVideoComposerException.CleanupIncomplete` reports honestly whether termination of the started process tree was confirmed. The composer and probe also reject any run whose result has `CleanupIncomplete=true` (pipes not drained or termination unconfirmed), even with exit code 0.
- Residual risks of the Job Object design: (1) `Process.Kill(entireProcessTree)` failure is now covered by `TerminateJobObject`, but `TerminateJobObject` itself can fail (access denied by an EDR, process protection); the runner then reports `CleanupIncomplete=true` after a 5 s bounded wait and closing the Job (`KILL_ON_JOB_CLOSE`) is the last resort, which is not observable if the host process itself is killed first. (2) A descendant that explicitly breaks away is impossible here (no `JOB_OBJECT_LIMIT_BREAKAWAY_OK`), but a driver/OS-created process outside the Job (for example `conhost.exe`, the console host, which exits asynchronously after the last attached process) is not a member; tests poll it for bounded disappearance. (3) The three pipe write ends are inheritable between `CreatePipe` and their close right after launch; a concurrent `Process.Start` elsewhere in the same host that inherits all inheritable handles could keep a pipe open, which is detected as a drain timeout (`CleanupIncomplete=true`, fail-closed) rather than a hang. (4) Windows 10 / Server 2016 or later is required for `PROC_THREAD_ATTRIBUTE_JOB_LIST`; older systems fail closed. (5) The `CreateProcessW` command line is built with `CommandLineToArgvW` quoting; the real argv round-trip test covers spaces, quotes and trailing backslashes, not every possible Unicode edge.
- The held-handle guarantee covers files the composer opened. The directory that holds them is not locked.

## Deferred (not required for this task)

Arbitrary executable resolution, long-path support, sub-5 ms timing, 44.1 kHz boundary precision.

## Verification

Local Linux: contract tests only (342 passed). Windows CI run 38022563554 on 30d29411 passed all required markers (earlier runs 1–4 failed on test-side issues fixed in the follow-up commits). Native Windows verification is the GitHub Actions run of `c009b-windows-master-mux-hardening.yml`; the required markers are `MASTER_MUX_UNIT`, `MASTER_MUX_REAL_WINDOWS`, `MASTER_MUX_HARDENING_UNIT` and `MASTER_MUX_HARDENING_REAL`, all `PASS`. Anything not observed there is UNVERIFIED.

## Job Object evidence (Windows CI)

- Attribution, run 38643441946 (`6caea913`): root `ffmpeg.exe` pid 5592 had children `conhost.exe` and `ffmpeg.exe` (pid 976) before the kill. With only the single-process fallback the root exited and pid 976 survived with `ppid=5592`, `descendant_of_root=True`. The leftover belonged to the spawned command, not to unrelated runner activity. The exact reason `ffmpeg.exe` spawns an `ffmpeg.exe` child (launcher shim vs. the build's own behavior) is UNVERIFIED.
- Superseded fix, run 38644278292 (`6eb752ca`, post-start assignment): all four forced-failure paths (NotSupported-throwing killer and no-op killer, each on timeout and on cancel) saw 1 `ffmpeg.exe` child before the kill and `owned_live_descendants_after=0` afterwards, with timeout/cancel semantics preserved. The original markers (3 profiles, zero narration, bounded and failure, held handles) stayed `PASS`.
- Fail-closed, run 38666747613 (`243578a7`): atomic Job launch. The four forced-kill paths still show `owned_live_descendants_after=0`. New native negative tests: `MASTER_MUX_FAILCLOSED_JOB_CREATE` and `_ENROLL` (the system rejects a bogus Job handle; no new ffmpeg child process started, killer never called, `CleanupIncomplete=false`), `_VERIFY` (enrollment verification fails while tree kill throws: root 9856 had 2 live descendants, `owned_live_after=0` after Job termination), `_SUPPRESS_TERMINATION` (all termination suppressed: `CleanupIncomplete=true` reported honestly, then 0 owned live processes after the Job is closed), `_ARGV_ROUNDTRIP`, and the unit marker `_UNIT_CLEANUP_INCOMPLETE` (composer rejects exit 0 with unconfirmed cleanup, no output). The original markers, 3 profiles, zero narration, bounded-and-failure, held handles, timeout and cancel stayed `PASS`. Earlier runs 10 and 11 failed on the CA1838 analyzer (`StringBuilder` in P/Invoke) and a conhost timing assertion; both fixed.
