# PicotooPet — Blockout optional previs V1.1

**Status:** Code-only candidate. No real installation/export test has occurred on the owner's Windows machine.

**Purpose:** A detachable geometry/camera planning aid, not a new production system, queue, database, agent or approval layer. Existing Character/Scene Bible, MASTER, Mac Core, Windows Worker and GPU HOLD stay authoritative.

## Grounded upstream interface

Official: https://github.com/wassermanproductions/blockout
MCP guide: https://github.com/wassermanproductions/blockout/blob/main/mcp/README.md
Windows prerelease: https://github.com/wassermanproductions/blockout/releases

Blockout v5.0.0 desktop prerelease includes a Windows x64 installer. Its bundled local MCP bridge controls the **already running** app via localhost and a bearer token. Documented tools include get_state, list_assets, add_entity, add_actor_mark, new_shot, add_camera_mark, screenshot and preset operations. **There is no documented MCP tool for exporting a shot package.** Export through the Deliver GUI, not by inventing a headless interface or mouse automation.

## One scene, three camera angles — single isolated pilot

1. Download from the official GitHub release and verify its published checksum. The Windows binary is unsigned. Do not install into ComfyUI or replace the existing Worker.
2. Start Blockout. Connect the existing Windows Codex/Claude MCP client to its bundled bridge:
   %LOCALAPPDATA%\Programs\Blockout\resources\mcp\blockout-mcp.mjs
   The MCP client needs Node installed and a correct absolute path.
3. With get_state and list_assets, place a simple dog, doorway and dining table. Choreograph ONE four-second dog path and then use THREE shots inside the same scene with different cameras: wide, side, front. Use a scene preset rather than rebuilding a kitchen for each shot.
4. In the Blockout Deliver GUI, export each shot package once. These are coverage views of one movement, **not** three chronological repeats of the movement.
5. From the PicotooPet repository root, run the read-only checker with the three actual exported folders (quote paths that contain spaces):

        # 验证三个 Blockout 导出包，预期每镜四秒、每秒二十四帧。
        python scripts/windows/blockout_previs_verify.py --seconds 4 --fps 24 "D:\BlockoutPilot\Shot-Wide\export-01" "D:\BlockoutPilot\Shot-Side\export-02" "D:\BlockoutPilot\Shot-Front\export-03"

6. Read the printed JSON. Compare actor_paths_match and camera_views_differ. Verify the doorway/table geometry manually in the Blockout scene. Save the Blockout scene preset or project as **existing Job-derived evidence** once practical.
7. Any unavailable/incompatible export is OPTIONAL_SKIPPED. Continue with the original first-frame/prompt video pipeline; never block normal production waiting for Blockout.

## What a validation result means

- PASS: Required metadata, prompt/readme, clean reference MP4 and the available video streams were checked.
- WARN: Optional depth, stills or blocking evidence was absent or Blockout itself reported motion warnings.
- FAIL: Malformed metadata, unsafe links, missing video, incorrect duration/fps or unmatched depth pass.
- UNAVAILABLE: ffprobe could not run. This is never interpreted as PASS.

Even PASS **never authorizes** generation, proves a Master identity, proves scene geometry, certifies a ComfyUI workflow or changes GPU HOLD.

Blockout metadata schema 1 gives camera and subject mark tracks, shot timing and profile, **but not the full scene geometry or a PicotooPet scene ID**. Comparing three actor trajectories cannot prove the table or doorway has not moved.

The bundled ComfyUI workflow JSON is *untrusted* until checked against the installed Windows ComfyUI node and model versions. Never import it automatically into the production graph. Maintain approved Maotai MASTER frames separately from the grey-box dog proxy. A video I2V workflow may continue to use only the real identity first frame plus an improved camera/motion prompt.

The final 832×480/24fps contract is not identical to Blockout's ordinary 16:9 preset. Allow differing previs resolution but verify the final framing/crop before actual production.

## Integration boundary

**Phase A (this PR):** A standalone stdlib-only, read-only verifier plus offline tests and instructions. No production database, schema, queue, GPU runner, service or UI is changed.

**Phase B (only after real export passes):** Link exported files and SHA digests to the current Job-derived asset area using existing artifact IDs. A single optional motion-reference association may be added only if existing generic asset links cannot express it. No second scheduler or agent.

**Phase C (only with A/B improvement):** Test a complex shot with and without previs. Record manual operations, setup minutes, spatial continuity errors, video retries and GPU seconds. Keep Blockout disabled by default unless it materially reduces total work.

Licensing/packaging: preserve Blockout's Apache-2.0 NOTICE if redistributing; review its bundled FFmpeg GPL terms and unsigned prerelease status separately.

## Evidence still required on owner's Windows machine

- [ ] Installed executable and release checksum verified.
- [ ] MCP connects to the live app without exposing a LAN port.
- [ ] One scene/one actor path/three genuinely different camera angles.
- [ ] GUI-exported MP4, depth MP4, PNG stills and metadata pass local ffprobe.
- [ ] Kitchen scene geometry and Maotai identity references remain consistent.
- [ ] Wan/LTX input compatibility tested on the *actual* workflows (not upstream claims).
- [ ] A/B reduction in total effort or improved continuity demonstrated.

**No live owner's Windows, Blockout MCP, GPU or real export tests have been performed yet.**
