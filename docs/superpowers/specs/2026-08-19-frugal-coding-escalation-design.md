# Frugal Coding Escalation Design

## Purpose

Add a conservative, Core-owned decision layer that decides whether a coding-class task should stay local or spend one bounded external coding-agent session. Reuse the existing Codex provider path, add a symmetric Claude Code adapter, and keep Mac Core as the only source of truth.

This design does **not** change the existing research/content/video architecture. Research Gateway remains read-only and Web ChatGPT upload remains manual.

## Frozen boundaries

- Windows Control Center can submit goals and read decisions/results, but cannot directly choose a provider, model, shell command, budget, worktree, tool list, or retry count.
- Mac Core owns provider eligibility, scoring, confidence, budget state, provider choice, audit, and the immutable decision digest.
- Mac Worker executes only fixed registered task types and fixed argv. No arbitrary provider command, shell, browser, GitHub write, network tool, or unrestricted environment forwarding is added.
- Codex and Claude Code are eligible only for coding-class work such as repository maintenance, bounded code repair, technical diagnostics, and approved implementation handoffs. Product research, content analysis, consumer research, and video-creative goals remain in the Research Gateway/local-analysis/Web-GPT handoff pipeline and are not eligible for coding agents.
- External provider execution is local-worktree scoped, one session at a time, no automatic retry, no auto-purchase, no auto-upgrade of plan/model/budget, and no credential capture.
- The system may detect CLI readiness, but user login/authentication remains a real-machine action.
- Natural Motion V2 release gates remain untouched.

## Architecture

```text
Goal / validated local coding result
            |
            v
Mac Core: Frugal Escalation Arbiter
  - coding eligibility gate
  - deterministic local quality score
  - conservative confidence band
  - historical provider Wilson 95% CI
  - risk score
  - budget state
  - provider readiness facts
            |
      +-----+----------------------+
      |                            |
      v                            v
LOCAL_ONLY                 one chosen provider
                              Codex / Claude Code
                                      |
                                      v
                           isolated Git worktree
                           fixed low-budget adapter
                                      |
                                      v
                           local return validation
                                      |
                         +------------+-----------+
                         |                        |
                       PASS              FAIL / UNCERTAIN
                         |                        |
                    stop spending        second provider only
                                         if policy explicitly
                                         permits and budget remains
```

## Decision model

### 1. Deterministic local quality score

The arbiter accepts bounded numeric signals owned by Core/validators. Initial factors:

- schema/contract validity
- evidence or diagnostic coverage where applicable
- test/validator outcome
- unresolved contradiction count
- local model self-confidence, capped so it cannot dominate the decision
- retry/failure history
- task risk and blast radius

The score is normalized to `0..100`.

### 2. Conservative confidence band

The immediate band is a decision interval, not a statistical confidence interval. It is derived deterministically from the local score and penalties for missing validation, evidence conflict, low coverage, high risk, and model-only evidence.

Stored fields:

- `confidence_center`
- `confidence_lower`
- `confidence_upper`

All are `0..1`. The lower bound drives escalation decisions.

### 3. Historical provider Wilson interval

Provider performance is based only on durable outcomes from comparable coding sessions. Success means the provider return passed local validation and the final result was accepted (or an equivalent terminal success fact). For `successes` of `trials`, the arbiter computes a two-sided Wilson 95% interval. With no trials, the history is explicitly `insufficient_history`; it is not treated as 100% or 0% reliable.

Stored per provider:

- `sample_size`
- `success_count`
- `success_rate`
- `wilson95_lower`
- `wilson95_upper`
- `history_sufficient`

### 4. Frugal provider utility

Provider selection is deterministic and conservative. The utility uses:

- expected quality uplift
- historical Wilson lower bound
- readiness
- cost/budget penalty
- latency penalty
- permission/risk penalty
- second-provider penalty

No provider is selected unless its utility exceeds a frozen threshold.

## Initial frozen thresholds

- `confidence_lower >= 0.80` and local validators pass -> `LOCAL_ONLY`; external coding agents are prohibited.
- `0.62 <= confidence_lower < 0.80` -> provider evaluation is allowed only for coding-class tasks and only if budget/readiness gates pass.
- `confidence_lower < 0.62` -> provider evaluation may occur, but still selects at most one provider initially.
- Default provider session budget per Goal: 1 external session.
- Absolute maximum per Goal: 2 external sessions, only when the first return fails/uncertain local validation, task impact warrants another attempt, and a second provider has positive utility above threshold.
- Automatic retries per provider: 0.
- Concurrent external coding sessions: 1.
- Cold start tie-break: existing verified Codex path first; Claude Code is the alternate. Once sufficient provider history exists, historical utility may override this tie-break.

## Durable decision record

Add a Core-owned immutable `ProviderEscalationDecision` projection with:

- `decision_id`
- `goal_id` or source identifier
- `task_class`
- `eligibility`
- `local_quality_score`
- `confidence_center/lower/upper`
- `risk_score`
- `reason_codes`
- `candidate_provider_scores`
- `provider_history`
- `budget_state`
- `chosen_provider` (`none`, `codex`, `claude_code`)
- `policy_version`
- `decision_digest`
- timestamps

Clients cannot submit these fields as authority.

## Provider contracts

### Codex

Reuse the existing `provider.codex.handoff-v1` path and existing isolated worktree/return validation. Keep bounded `workspace-write` sandboxing and fixed non-interactive execution. Do not add open network or arbitrary tools.

### Claude Code

Add `provider.claude-code.handoff-v1` with a fixed adapter. The adapter uses non-interactive print mode and machine-readable output. The argv is source-controlled and callers cannot append flags.

Initial permission policy:

- fixed working directory = isolated session worktree
- fixed turn limit
- fixed timeout/output cap
- no automatic retry
- explicitly disallow Bash, WebFetch, WebSearch, NotebookEdit, Task/agent spawning, MCP tools, and other network/shell capabilities
- allow only the minimum file-read/edit capabilities required for a bounded patch lane
- PicotooPet Worker, not Claude Code, runs local tests/validators after return
- never use `--dangerously-skip-permissions`

If the installed Claude Code version cannot satisfy the frozen permission contract, readiness is `policy_blocked` and no real session is started.

## Readiness

Readiness facts are non-secret and owned by Mac Worker/Core:

- executable present
- supported CLI flags/version contract
- authenticated/not-authenticated when safely observable without reading credentials
- policy compatible

No installer logs in, captures tokens, copies browser sessions, or modifies account settings.

## Windows projection

Windows receives a read-only explanation such as:

- `本地 86 分，置信带 0.81–0.90；本地验证通过，因此未使用外部 Coding AI。`
- `本地 61 分，Codex 的保守效用最高，已允许 1 次受控 Session；Claude Code 未调用。`

Windows cannot override the provider choice or enlarge the budget through this surface.

## API and task types

Keep the existing provider APIs where possible. Add only the minimal read-only decision/readiness projection required by Goal Center/Deep-AI status.

Worker fixed task types:

- existing: `provider.codex.handoff-v1`
- new: `provider.claude-code.handoff-v1`

The arbiter itself is a Core service, not a new arbitrary Worker executor.

## Error handling

- Unsupported/non-coding task -> deterministic `NOT_ELIGIBLE_FOR_CODING_AGENT`, local path continues.
- High-confidence local result -> `LOCAL_ONLY`, no provider work queued.
- CLI missing -> provider `unavailable`; consider another provider or local/manual path.
- CLI not authenticated -> `not_authenticated`; no provider session starts.
- CLI flags/version incompatible with frozen policy -> `policy_blocked`.
- Budget exhausted/unknown under a policy requiring known budget -> no external session.
- Provider timeout/failure -> immutable failed attempt; no automatic retry.
- Return fails local validation -> mark failed/uncertain; second provider is considered only through a fresh Core decision under the absolute two-session cap.

## Testing requirements

TDD is mandatory.

Unit/contract tests must prove:

1. non-coding goals never call Codex/Claude Code;
2. high-confidence validated local work never calls either provider;
3. Wilson 95% CI is correct for zero, small, and larger samples;
4. sparse history is penalized conservatively;
5. one provider is selected deterministically from the same inputs;
6. one provider PASS stops all further spending;
7. second provider is allowed only after failed/uncertain validation and within the two-session cap;
8. clients cannot choose provider/model/budget/flags;
9. Claude Code argv is fixed and excludes dangerous permission bypass, Bash, web/network and MCP capabilities;
10. Codex existing safety limits remain intact;
11. Core/Worker packages contain the arbiter, Codex adapter, Claude Code adapter, readiness verifier and policy files;
12. Mac Core, Mac Worker, Windows Control Center regressions remain green;
13. formal Windows release may remain blocked only by the existing Natural Motion V2 asset gate, which must not be bypassed.

## Real-machine acceptance

After CI/install package verification, the only expected user participation is:

1. install/use the generated Mac Core + Worker package;
2. complete Codex CLI login if readiness reports `not_authenticated`;
3. complete Claude Code login if readiness reports `not_authenticated`;
4. run the provided strict live verifier/smoke once.

No credential material should be pasted into PicotooPet or into test reports.
