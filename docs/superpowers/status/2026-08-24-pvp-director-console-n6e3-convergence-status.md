# PVP Director Console N6E3 Convergence Status — 2026-08-24

## Authority

- Frozen architecture: `PVP-DIRECTOR-CONSOLE-NATIVE-V2.0-FREEZE-1`.
- Development branch: `feature/pvp-director-console-native-v2-prebuilt-release`.
- Draft PR: `#42`; keep Draft / Open / Unmerged until real-machine installation acceptance.
- Canonical remains read-only; delete remains tombstone/soft-delete only; no permanent purge.
- No `/prompt`, `queue_prompt`, model download, user-PC `.NET` build/publish, SDK install, pip install, or conda install.

## User-priority order

Later user requirements override earlier ones. Current order is:

1. **Stable connection and visible recovery/progress** — Director Core failures must recover automatically instead of leaving the UI apparently disconnected or idle.
2. **Chinese-first simplified Native UI** — remove unnecessary English and reduce top-level operational complexity.
3. **Single delete + batch selection + batch delete + batch restore** — all mutations remain human-directed, previewed, revision-checked, atomic, and tombstone-based.
4. **Reliable prebuilt Windows delivery** — user machine must not compile source; final installer must carry the exact CI-built EXE and verified Director Core payload.
5. **LookDev / art-direction / First-Frame work remains paused** until the Director Console control-plane experience above is release-valid.

## Verified repository state

### Native N6E3 implementation exists

The branch contains the approved N6E3 Native patch/deltas and runtime contracts covering:

- Chinese lifecycle/display labels and simplified shell behavior;
- Core supervisor/recovery markers and persistent diagnostics;
- batch selection actions and Native client methods;
- no top-level media-submission calls.

The previous Windows convergence run `32520536720` successfully produced and self-tested the Native EXE. However, its uploaded artifact contained only:

- `native-publish/PVP Director Console.exe`;
- `native-self-test.json`;
- `native-exe.sha256`.

It was **not** a complete installer payload.

### Backend N6E3 patch exists

`pvp/director-console-native-v2-bootstrap/n6e3-backend/n6e3.backend.patch.gz.b64` contains the approved atomic batch-delete / batch-restore backend delta and its tests.

### Final package builder/verifier exist

The branch contains:

- `build_n6e3_prebuilt.py` — deterministic final N6E3 package builder;
- `verify_n6e3_package.py` — manifest/hash/ZIP/safety/backend-endpoint verification;
- N6E2.2 deterministic installer transaction to be relabeled and packed as N6E3 only after the full payload is assembled.

## Current RED gate / exact blocker

Commit `671c02d882aa60d0f18c06adcde662a088e6f9d1` extended the Windows workflow so that an artifact can no longer be called Installer-Green unless it also:

1. applies the N6E3 backend patch;
2. runs backend regression + compile gates;
3. builds/publishes/self-tests the Native EXE;
4. creates the deterministic final N6E3 installer ZIP;
5. verifies package manifest/hash/ZIP/backend contracts;
6. smoke-runs the exact final CMD installer from a Unicode + spaced path.

Windows run `32761049201` correctly failed at the backend-input boundary. The reconstructed Native source bundle does **not** contain:

`payload/producer/extensions/director_console_native_v2`

while the backend patch was authored against the N6D4 full-package layout under exactly that path.

This proves the missing piece is the **pinned Director Core baseline source payload**, not another WPF/compiler fix and not another seed/test run.

## Source availability rule

Do not reconstruct the missing Director Core baseline by guessing from patch context. The N6D4 full package is the expected baseline, but its authoritative source bytes are not currently committed on this branch. The release workflow stays RED until that baseline is pinned and hash-verifiable.

## Next convergence step

Once the N6D4 Director Core baseline bytes are available, the implementation path is fixed:

1. pin the Director Core baseline as a deterministic source bundle + SHA in this isolated bootstrap subtree;
2. reconstruct Native source and Director Core source as separate inputs;
3. apply the existing N6E3 backend delta to Director Core;
4. run backend regression and atomic delete/restore tests;
5. build/publish/self-test Native on `windows-2025`;
6. assemble the complete final N6E3 installer from the exact same-run EXE + verified Core payload;
7. run clean-package verification and exact-entry Unicode-path smoke;
8. only then expose the installer for real-machine acceptance.

No older `N6E3-Green` native-only artifact should be presented as the final installer.
