# Research Gateway 2.3.27.1 Release Evidence

## Release candidate

- Source commit: `ec143e5d1b294cd5dfdd2c413af3ae502a7ea3a7`
- GitHub Actions run: `31909645657`
- Workflow run number: `14`
- Native runner: `macos-15-arm64`
- Package: `PicotooPet-ResearchGateway-2.3.27.1-arm64.tar.gz`
- Package SHA-256: `06fba646942e3bf8deb47187a44d8454e3685332ab66f0c759906e1b6f1b8e01`
- Uploaded artifact: `PicotooPet-ResearchGateway-2.3.27.1-arm64-14`
- Artifact ID: `9253300808`
- Artifact ZIP SHA-256: `c17face79067d6e9fda00f05306760fe54593e698654db74c85dea337b3a5681`

## Verification

The native macOS release workflow completed successfully with the following evidence:

- Research Gateway focused unit/contract suite: `8 passed`.
- Ruff: all checks passed.
- Python compilation: passed via `python -m compileall -q scripts research_gateway`.
- Full Python regression: `742 passed in 31.19s`.
- Research Gateway shell syntax validation: passed.
- Package build: `RESEARCH_GATEWAY_BUILD=PASS`.
- Tarball SHA verification: `OK`.
- Isolated fixture install, health check and uninstall: `RESEARCH_GATEWAY_PACKAGE_FIXTURE=PASS`.
- Artifact upload: success, six evidence/package files uploaded.

An independent post-download inspection also confirmed that the package SHA-256 matches the CI value and that every file listed in `release-manifest.json` matches its declared SHA-256 and byte size.

## Frozen release properties

- Version: `2.3.27.1`.
- Target: macOS arm64.
- Research Gateway remains process-isolated from Mac Core.
- Capability plane is read-only.
- Browser cookies are not embedded in the package.
- Xiaoyuzhou is disabled/not packaged.

## Known pre-existing governance drift

`AGENTS.md` references `scripts/verify_alignment.py --ci`, but `scripts/verify_alignment.py` is not present in this repository branch and repository search returns no implementation. The existing `scripts/verify_project_goal_integrity.py` is a Windows formal-package goal gate and is not an equivalent macOS Research Gateway alignment verifier. The Research Gateway workflow therefore records:

`ALIGNMENT_VERIFIER=NOT_PRESENT_PREEXISTING_GOVERNANCE_DRIFT`

and continues with repository Python compilation and the full regression suite rather than silently substituting an unrelated verifier.

## Operational note

Hosted CI validates the installer payload and isolated fixture lifecycle but does not contain the user's authenticated Chrome profile. Browser-session platform acceptance remains an installation-time verification step using `VERIFY_RESEARCH_GATEWAY.command` on the production Mac Research node.
