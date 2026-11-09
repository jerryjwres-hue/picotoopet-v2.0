# P0 #237 · Owner Review SSH stdio transport candidate

**Status: CODE CANDIDATE ONLY / TRANSPORT_SECURITY=BLOCKED / NOT DEPLOYED**

## Why stdio forwarding instead of a Windows listening port

The old proposed `ssh -L 127.0.0.1:<port>:127.0.0.1:8765` exposes a local
listener and leaves a same-host port-rebinding risk when an SSH process exits.
An HTTP client that accepts any Windows loopback endpoint cannot verify that the
listener is the authenticated Mac SSH tunnel.

OpenSSH `ssh -W 127.0.0.1:<actual Core port>` forwards stdin/stdout directly
inside the authenticated SSH channel, with **no localhost port listener**.
The .NET `SocketsHttpHandler.ConnectCallback` candidate supplies this SSH
process stream as the HTTP connection. Its internal `.invalid` authority is
never resolved by DNS and is not an alternative network destination.

## Local, fail-closed contract

Added isolated code (not yet called by the production OwnerReviewClient):

- `OwnerReviewSshStdioProfileVerifier`: validates absolute protected file
  paths, one exact ED25519 host key alias, and a separately approved expected
  SHA256 host-key fingerprint. Rejects unknown aliases, wildcard/extra keys,
  malformed keys, missing keys and fingerprint mismatches.
- Uses system `%WINDIR%\System32\OpenSSH\ssh.exe` only, not PATH or a
  shell. `ProcessStartInfo.ArgumentList` prevents parameter injection;
  user SSH config and ProxyCommand/ProxyJump are disabled; host key updates
  and passwords are forbidden; no interactive prompts, `-L`, `-R` or
  `-D` listeners.
- `OwnerReviewSshStdioCandidate`: no proxy or redirect. A custom .NET
  `ConnectCallback` rejects endpoints other than the internal synthetic
  authority and transfers each HTTP connection through a scoped `ssh -W`
  process stream. Exit or teardown destroys the pipes; there is **no**
  automatic fallback to local TCP or LAN HTTP.
- Does not create a real `OwnerReviewClient`, read a DPAPI Bearer, change
  the existing device token, modify Core/Worker/GPU or activate a UI. The
  existing production security gate `EncryptedMacTransportAccepted=false`
  and locked Goal Center preview remain unchanged.

## Device-side read-only preflight (OPTIONAL, no live connection)

These small scripts **are not device authorization** and have never run on the
owner's Mac or Windows. GitHub CI only parses their syntax; a CI Runner is not
a substitute for the user's devices. They must be run only after explicit
permission for the specific device check.

- Mac: `sh scripts/owner_review/readonly_mac_ssh_preflight.sh`.
  Checks local SSH ED25519 **public** host-key fingerprint (no private key),
  launchctl policy hint, and socket presence on SSH 22 / Core 8765 / 8766.
  None of these prove actual sshd authorization or Core identity.
- Windows PowerShell: `powershell -NoProfile -File scripts/owner_review/readonly_windows_ssh_preflight.ps1`.
  Checks built-in system OpenSSH executable and version. Does **not** inspect
  any real owner credential, DPAPI data, private SSH identity, known_hosts,
  Mac IP/DNS address or endpoint.

For auditing, preserve only the explicit `CHECK_SCHEMA=...` and
`DEVICE_ROLE=...` key-value results; **do not paste full local terminal
history, IPs, passwords, SSH private keys or bearer tokens** in PR comments.
If Mac SSH host fingerprint is available, the owner should verify it locally
and use it only inside the protected provisioning process.

Statuses such as `NOT_OBSERVED_NOT_PROOF_OF_DISABLEMENT` or
`UNVERIFIED` mean STOP for that dimension, not FAIL for the device.
A local listener at 8765/8766 is **not** authenticated evidence that the
listening process is PicotooPet Core. Its source default is 8765, but runtime
may override it. A verified real Core health/identity call is still required.

## Before ANY live owner credential can be used

**Not performed by this PR. Requires explicit operator approval and device evidence.**

1. Read-only verify Windows system OpenSSH binary/version and actual Mac Core
   port (source default 8765; runtime `PICOTOO_API_PORT` can override it).
2. Determine whether macOS Remote Login / sshd is already enabled. Do not
   silently enable it or open a firewall.
3. The owner must verify the Mac SSH ED25519 host-key fingerprint **out of
   band on the Mac itself**. A value from `ssh-keyscan` alone is not proof.
   Save the exact approved public key in a protected one-line known-hosts
   file matching alias `picotoopet-owner-review-mac`.
4. Explicitly provision a restricted SSH identity on Windows and verify
   the Mac sshd allows only the required `direct-tcpip` forwarding to
   Core loopback. Prefer a dedicated non-admin SSH account and SSH server
   restrictions. Ensure host-key and identity files have user-only ACLs.
5. Prove real pinned-host handshake, authenticated SSH user, fresh
   connection, no local port listener, and read-only Core health/Proposal.
   Confirm Core sees a genuine loopback peer. An HTTP success alone is not
   proof of SSH authentication without the exact process/host-key evidence.
6. Independently provision the separate Core `OwnerPrincipal` registry
   grant and Windows DPAPI Owner Review Bearer, with exact subject scope,
   explicit permission and revocation mechanism.
7. Review and approve a **separate production factory wiring PR** that
   uses the authenticated process stream, not arbitrary
   `http://127.0.0.1` and not the existing `LoopbackOnly` mode. Only then
   may owner-specific, read-only Proposal be tested. Preview/Commit require
   an additional explicit owner approval. No automatic Commit.

## CI acceptance and limitations

Synthetic Windows native smoke verifies the SSH command shape, pinned
host-key calculation and negative cases (wrong key, alias injection,
missing files, no listener, no proxy/redirect). **No SSH session is
established in CI and no real Mac access occurs**. Thus it cannot
establish Windows→Mac authentication, runtime Core port, SSH server
restrictions, trusted device configuration or Owner Review production
readiness.

The macOS Core, Windows same-EXE Worker, existing production QA and
static pet story policy are unchanged. All resulting PRs stay Draft;
no Goal, Ollama, model token or GPU use.

## Typed pinned-SSH-stdio client factory and NTFS ACL gate (code-only, default locked)

Added after the accepted live transport candidate (`TRANSPORT_SECURITY=PASS_CANDIDATE`). This is
**not** a production activation: `EncryptedMacTransportAccepted` and the new
`PinnedSshStdioActivated` stay `false`, the Goal Center review stays locked, and no owner
Bearer/DPAPI credential is read anywhere in construction.

- `OwnerReviewTransportMode.PinnedSshStdio` is distinct from `Mock`, `LoopbackOnly` and
  `VerifiedEncrypted`. The gate accepts only the fixed synthetic authority
  `http://owner-review-ssh-stdio.invalid/` (never resolved by DNS).
- `OwnerReviewClient.CreatePinnedSshStdio(profile, credentials, activation)` is the only way to build
  it. It accepts no handler and no base URI, always uses
  `OwnerReviewSshStdioCandidate.CreateIsolatedHandler`, and needs an
  `OwnerReviewSshStdioActivation` token that production cannot obtain while the gate is locked.
  The public constructor refuses this mode (with or without an injected handler).
- `OwnerReviewProtectedFileAcl` verifies the effective NTFS owner and DACL of the private key,
  the pinned known_hosts and their immediate parent directory: owner and every allow ACE must be
  the current user, SYSTEM or Administrators; Everyone/Users/other principals or a null DACL fail
  closed (`..._ACL_TOO_BROAD`); unreadable/missing/reparse/relative paths and non-Windows hosts fail
  closed (`..._ACL_UNVERIFIED`). It reads descriptors only and never file contents.
- `BuildPinnedCommand` rejects duplicated `-o` option names (OpenSSH keeps the first value of a
  repeated option, which hid a wrong-alias test on 2026-11-08).
- Still required before any live owner session: a single read-only binding of the Mac Core PID/executable
  SHA to the authenticated health/trace response (`CORE_RUNTIME_IDENTITY=CONSISTENT_NOT_PROVEN` today),
  a separate OwnerPrincipal grant, a separate DPAPI owner credential and a separately reviewed UI
  activation. Preview/Commit need explicit owner approval.
## Production wiring (default locked; explicit authorization required)

`OwnerReviewLiveWiring.TryOpen` is the only path from the Goal Center "Owner Review" button to a live
client. It runs only on that click (never at startup, never creates a Goal, Worker or task) and stays
locked while `OwnerReviewTransportGate.PinnedSshStdioActivated` is `false` (nothing on disk is read).
With the gate open it additionally requires an owner-authored, NTFS-protected
`%LOCALAPPDATA%\PicotooPet\OwnerReviewSsh\owner_review_live_profile.json` (strict
`owner_review_live_profile.v1`: `mac_host`, `mac_user`, `ssh_port`, `core_port`,
`expected_host_key_fingerprint`; the key and pinned known_hosts are fixed file names beside it) and
then builds the client only through `OwnerReviewClient.CreatePinnedSshStdio`. Mock, plain HTTP and
injected handlers are unreachable. The OwnerPrincipal credential is read per request from the dedicated
DPAPI store; a missing credential refuses every operation, and the device token / Worker Ed25519 or DPAPI
identity is never used.

Wire contract: all request/response fields of proposal, preview and commit match Mac Core
`5c51fdb3` (frozen OpenAPI blob sha256 `bfcbb899…7789a`, checked by the existing smoke test).

Minimal authorization to activate (all separate decisions, none made by this change):
1. Deploy a Mac Core containing #235 (and #242 for Creative scheduling) and an OwnerPrincipal grant for the pet subject.
2. Owner enrolls the OwnerPrincipal credential in the panel (dedicated DPAPI store).
3. Owner writes the protected profile file above (host, user, ports, host-key fingerprint).
4. A reviewed PR flips `PinnedSshStdioActivated` to `true`, then a new Windows build is installed.
