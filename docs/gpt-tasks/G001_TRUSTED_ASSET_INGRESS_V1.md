# G001 — Trusted Asset Ingress v1 Architecture

Docs-only architecture task. Do not implement code.

Goal:
Design the smallest safe trusted asset ingress that can later unlock C006B EXISTING_ASSET without creating a second asset system.

Audit real repository code:
- PathPolicy / managed roots
- projects/project assets if any
- MCP list_assets contract
- Creative ShotPlan existing_asset_ref
- Production plan/compiler/package
- Windows/Mac transfer boundaries
- existing artifact stores and upload/download patterns

Must answer:
1. What exactly is a trusted asset identity?
2. Who imports/registers it: Mac Core or Windows?
3. How bytes move from Windows/user-selected file into a managed root without giving Core arbitrary path authority.
4. Required immutable facts: asset_id, sha256, bytes, mime, dimensions/duration, managed relpath, source/provenance, created_at.
5. How ShotPlan.existing_asset_ref binds to trusted asset identity.
6. How Production compiler resolves it without arbitrary paths.
7. How Windows receives/normalizes it to timeline-compatible WebM.
8. Restart/replay/idempotency/conflict semantics.
9. Symlink/reparse/traversal/TOCTOU controls.
10. Whether existing MCP list_assets can be reused or is only a registry stub.
11. Exact API/contracts required.
12. Exact files/modules likely touched.
13. Files explicitly forbidden.
14. Tests and acceptance criteria.
15. Minimal implementation slices, preferably C006B1 ingress then C006B2 execution if separation is useful.

Constraints:
- Mac Core source of truth
- no arbitrary user/GPT absolute paths
- no second Creative/Production pipeline
- no C006A TEXT_CARD changes
- no C007A narration changes
- no C004 changes
- no S002 networking changes
- no Maotai/UI
- no deploy/macos
- no code implementation

Deliver:
docs/architecture/video/G001_TRUSTED_ASSET_INGRESS_V1.md

End with:
READY_TO_IMPLEMENT: yes/no
NEXT IMPLEMENTATION SLICE
BLOCKERS
FILES OWNERSHIP
