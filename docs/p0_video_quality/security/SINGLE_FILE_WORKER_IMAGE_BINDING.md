# Issue 175: single-file image binding

Frozen parent: `5a88c302e0eaa403831e24952fc0f31d1ddd0b98` (#173 / Draft #174).
This is a chained PR: #174 must be reviewed/integrated into controller #149
before selecting this dependent change. Target remains
`integration/p0q2-quality-staged-20261029`; no main merge or release.

The pre-fix strict cross-publish reproduced IL3000 at the two production
`Assembly.Location` reads. The published test now requires ACCEPTED instead of
the previously demonstrated single-file rejection. No production Location call,
reflective replacement, compiler-warning suppression or warning reclassification
is used by the new measurement.

The implementation retains OS/Environment path agreement, canonical local NTFS
and PE checks, directory/file pins, original-filename resources, file identity,
stable SHA256 and current-image rechecks. Entry validation now runs under the
image lease. It admits only the known Desktop and native SmokeTests entry names
in the default assembly load context, with matching OS image basename and exact
normalized `AppContext.BaseDirectory`. No caller selects measurement path/hash.

Both forms require the SDK apphost marker and embedded managed entry filename
in the bounded native PE. Offset zero requires an ordinary adjacent entry DLL;
a bundle requires its actual v6.0 manifest and unique entry assembly. In either
case metadata name, version and module MVID must match the real runtime entry.
The normal DLL is checked/pinned against reparse/path/file-identity changes.
Bundle manifest/name/count/ranges/read sizes are bounded; unknown formats,
compression or flags fail closed. The supported native extraction configuration
uses the uncompressed v6.0 format and no all-content extraction flag.
Format reference: .NET runtime v10.0.0 HostModel `Bundle/Bundler.cs`,
`Bundle/Manifest.cs`, and `Bundle/FileEntry.cs` (no added package dependency).

The scoped workflow runs the existing Same-EXE recovery/signing suite,
independent 28-case matrix and GUI ownership contracts in one Windows job, and
strict `--warnaserror` actual single-file Desktop publish/self-test in another,
on the same exact checkout SHA. The published process probe remains read-only:
no private keys, signing, nonce, HTTP, Worker or Comfy invocation. Real Ed25519
and DPAPI tests stay within the existing native SmokeTests suite.

Negatives cover absent/other/memory-loaded entry assemblies, wrong entry folder,
misleading native resources, substituted/reparse DLLs, malformed PE, generic and
renamed hosts, changed files and pin sharing. CLR renamed-muxer startup refusal
remains distinguished from managed measurement rejection.

Per-run JSON and matching-SHA CI results are the evidence. Local image binding
and locally signed EXE digests do not establish independent trusted Windows
execution or Comfy Journal attestation. DPAPI, nonce, approvals, Journal, factory
proof-required rejection and all GPU gates remain unchanged. Production I2V
stays BLOCKED. Formal Release/Maotai requirements are neither exercised nor
waived by technical publish acceptance.
