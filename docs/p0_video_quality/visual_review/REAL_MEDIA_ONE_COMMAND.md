# Real 3-shot CPU visual review — one local operator action

This is a read-only **review evidence** entry point over the existing
\`tools/p0_visual_review\` CLI, not a new QA authority, renderer, or image model.

## Windows operator

Prerequisites: Windows release SDK .NET 10, local \`ffmpeg.exe\` and \`ffprobe.exe\`
already on PATH, successfully paired Core Credential Manager token, **GPU HOLD**
and the \`.armed\` marker, a real Core Production Job with exactly three committed
hash-matching WebMs. Run from the already-reviewed source checkout:

\`\`\`powershell
# ── Read-only CPU evidence for the original frozen Job; no Comfy POST or LAN VLM.
& ".\tools\p0_visual_review\Invoke-ExactProductionReview.ps1"
\`\`\`

The script fetches exact immutable Core Job, Plan, and Package over three authenticated
GETs; checks status, lineage, PASS package, ordered shot/task IDs, real Windows
source bytes/SHA256; then builds and invokes the existing observer locally. It
does not modify the source videos, launch any GUI/Worker, change GPU HOLD,
download models, install binaries or transfer stills to Mac/Internet. This is
**operator-run locally**, not a remote action.

When successful, the script prints \`CONTACT_SHEET_PATH\`, \`REPORT_PATH\`,
\`SOURCE_SHOTS_SHA256_VERIFIED=3\`, and \`VISUAL_ACCEPT=UNVERIFIED\`. The contact
sheet is a private local 3x3 PNG with an immutable frame/shot map; **open it
and submit the actual stills for human evaluation** of identity/accessory
consistency, physics and support, scene layout, temporal progression and story
causality. The report is advisory, does not replace C011 QA, and the previously
rejected film remains human \`VISUAL_REJECT\`. Nine stills do not prove motion.

After real evidence, prioritize one targeted quality change per dominant
failure (reference-authorized I2V and three-image approvals if available;
otherwise Story Bible shot identity, causal states and prompts), measuring
human accepted videos / first-pass attempts and actual GPU time before/after.
A local VLM is **opt-in separately** only after verified installation, explicit
frame-transfer consent and calibration; never automatically auto-ACCEPT.

No user video, GPU, Mac Ollama, credentials, or hardware was accessed by this
source change. Missing or uncertain evidence must remain \`UNVERIFIED\`.
