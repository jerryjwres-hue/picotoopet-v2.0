# Research Gateway 2.3.27.1 Implementation Plan

1. Add RED unit/contract tests for the frozen `research.*` surface, read-only policy, subprocess isolation and package layout.
2. Add a PR-triggered native macOS workflow so the RED state is observable in GitHub Actions.
3. Implement the standalone gateway runtime with structured capability dispatch and injectable subprocess runner.
4. Add macOS install/verify/uninstall payload plus deterministic package builder and fixture smoke test.
5. Move the RED suite to GREEN, then run full Python regression, alignment verification, Python compilation and native package smoke.
6. Upload the architecture-specific package, SHA-256 and build report as a GitHub Actions artifact.
7. Update governance/handoff evidence and keep the branch ready for integration without wiring concrete adapters into Mac Core.

## Guardrails

- No Mac Core venv installation for Agent Reach/OpenCLI.
- No arbitrary shell input.
- No write operations in 2.3.27.1.
- No browser-cookie export or embedding.
- No Xiaoyuzhou dependency.
- Existing Approval Gate contract remains unchanged.
