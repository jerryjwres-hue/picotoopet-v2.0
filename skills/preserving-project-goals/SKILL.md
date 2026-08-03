---
name: preserving-project-goals
description: Use when tooling, CI, quota, platform access, signing, dependencies, deadlines, or implementation difficulty create pressure to change an already approved product goal or acceptance standard.
---

# Preserving Project Goals

## Overview

**阻断可以改变进度状态，不能改变产品目标。**

A delivery remains the approved product or it is not delivered. Changing the surface, host, architecture, integration point, install path, or acceptance gate to get something running is goal degradation, not problem solving.

## Required decision

Before any workaround, compare it with the approved goal:

- Same product form and daily user surface?
- Same host application and integration location?
- Same architecture boundaries and fact source?
- Same install, verify, rollback, privacy, and native-platform gates?
- Same user workflow and acceptance meaning?

If any answer is no, stop. The change needs **explicit user approval before implementation**. Do not build it first and ask later.

## Allowed response to blockers

Use one accurate status:

- `BLOCKED`: a required environment or dependency is unavailable.
- `UNVERIFIED`: implementation exists but a mandatory gate has not run.
- `DIAGNOSTIC`: evidence-only output that is not installable or complete.

Continue equivalent engineering work that preserves the target: tests, source fixes, static contracts, packaging preparation, evidence collection, or finding another truly equivalent native environment.

## Forbidden substitutions

Do not describe any of these as the formal deliverable without prior approval:

- native desktop → browser, localhost HTTP, WebView, Electron, CLI, or script UI;
- feature inside an existing app → separate Helper or second application;
- target-platform verification → cross-platform static checks;
- prebuilt installer → source build on the user's machine;
- mandatory lifecycle or safety gate → “temporary” manual verification;
- approved architecture → reduced prototype presented as complete.

“temporary,” “equivalent,” “fallback,” “helper,” “prototype,” “local,” and “diagnostic” are labels, not exemptions.

## Red flags — stop

- “At least it runs.”
- “This is faster.”
- “We can replace it later.”
- “The user only cares about the feature.”
- “CI is unavailable, so this is close enough.”
- “It is technically an EXE, even though it opens a browser.”

All mean the original goal is being negotiated under pressure.

## Completion rule

A substitute may be useful evidence, but **不得宣称完成**. Record the blocker, preserve the approved target, and resume only on a path that satisfies the original acceptance contract.
