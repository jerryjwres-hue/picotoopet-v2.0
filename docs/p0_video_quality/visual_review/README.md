# P0-Q2 #140: read-only, optional visual observation

Scope: an independent **diagnostic** CLI, NOT the official WPF UI, C011 receipt, scheduler, or automatic re-renderer. Source branch feature/p0q2-web-visual-critic-20261029 from frozen Preview156 1698fee9. The rejected 3-shot cat video remains human VISUAL_REJECT. Real user WebMs have not been accessed.

## Exact input

Provide one immutable visual_review.input.v1 JSON file containing a frozen Production Job UUID and exactly 3 ordered records. Each record: order (1, 2, 3), shot_id, task_id, relative_path under the approved Comfy output root, real sha256 (64 hex digits), bytes, expected_frames, expected_duration_ms, and action. Retrieve identity, exact hashes and frame/duration measurements from existing Core/Worker/Comfy evidence; **never fabricate or backfill values**. Example below has deliberate placeholders and is not executable evidence:

    {
      "schema_version": "visual_review.input.v1",
      "job_id": "64695948-fb1a-4793-815f-3f6ad4d4d536",
      "shots": [
        {"order":1,"shot_id":"REPLACE_SHOT1","task_id":"REPLACE_TASK1","relative_path":"REPLACE/shot1.webm","sha256":"REPLACE_WITH_REAL_64_HEX","bytes":0,"expected_frames":97,"expected_duration_ms":4000,"action":"cause: cat approaches product"},
        {"order":2,"shot_id":"REPLACE_SHOT2","task_id":"REPLACE_TASK2","relative_path":"REPLACE/shot2.webm","sha256":"REPLACE_WITH_REAL_64_HEX","bytes":0,"expected_frames":97,"expected_duration_ms":4000,"action":"action: cat interacts"},
        {"order":3,"shot_id":"REPLACE_SHOT3","task_id":"REPLACE_TASK3","relative_path":"REPLACE/shot3.webm","sha256":"REPLACE_WITH_REAL_64_HEX","bytes":0,"expected_frames":97,"expected_duration_ms":4000,"action":"payoff: product resolves problem"}
      ]
    }

## Focused offline native smoke (GitHub Windows runner only, no user device)

    dotnet build tools/p0_visual_review/PicotooPet.VisualReview.csproj -c Release --warnaserror
    dotnet run --project windows/desktop/tests/PicotooPet.QualityObservation.SmokeTests -c Release

No GPU, real media, Mac connection or Ollama inference in the smoke harness. Fake cat/scarf/lamp disagreements test the parser and fail-closed logic, not actual perceptual accuracy.

## Post-approval read-only operator procedure (not executed)

After the owner explicitly permits read-only access to exact three files, an operator may run a **separately prebuilt, unsigned review-only CLI** with five positional arguments: manifest JSON path, Comfy output root, entirely new evidence directory outside the Comfy root, ffprobe executable path, ffmpeg executable path. Example:

    PicotooPet.VisualReview.exe "C:\audit\manifest.json" "D:\ComfyUI\output" "C:\audit\evidence-001" "C:\ffmpeg\bin\ffprobe.exe" "C:\ffmpeg\bin\ffmpeg.exe"

A successful audit emits only in the new evidence directory: frames/frame_00.png ... frame_08.png (3 evenly sampled 320x180 stills per shot), contact_sheet_3x3.png, report.json. The report has grid-index to shot/task/timecode/file SHA256 correspondence, video frame counts, duration and immutable source digest. File names/timecodes are encoded in the JSON accompanying the sheet; rows are ordered shot 1, 2, 3. Hash source before/after, prohibit path traversal/reparse points and output overwrite. Contact-sheet generation is a CPU-only FFmpeg operation.

Optional **private-LAN Mac Ollama only**: the owner separately authorizes sending three scaled still images to a literal private IPv4 endpoint, and the operator appends:

    --allow-lan-vlm http://192.168.1.15:11434 qwen3-vl:4b --consent

This deliberately rejects public IPs, DNS, proxy/redirect and implicit model downloads. A successful tags call shows **installed** only; successful generate is **inference succeeded**, not visual correctness, and does not imply the model is persistently loaded. All output flags are untrusted. VLM can return only ADVISORY_REVIEW, REJECT_SUSPECT or UNVERIFIED; never visual ACCEPT. A model's uncertain/injected response remains advisory or UNVERIFIED.

## STOP and status

Wrong identity, count, source hash, bytes, counted frames, duration tolerance (250ms), reparse point, missing media, ffprobe/FFmpeg failure, mutated source, unexpected network/model behavior: UNVERIFIED, zero new Comfy POST, no source modification. User's actual cat film remains human-rejected; final MP4/C011 absence belongs to separate #143 investigation. No technical test here certifies coherent story, real physics, motion, reference identity or final C011 quality.

## Non-executing ZIP packaging proposal

After focused Windows native CI, a separately authorized Windows cloud job may run dotnet publish with win-x64 --self-contained true -p:PublishSingleFile=true -p:PublishTrimmed=false; package only the CLI plus this README, manifest template, exact source SHA and ZIP SHA256. Diagnostic-only unsigned ZIP, not an official Picotoo Pet AI.exe installer, no model weights, GPU code, Worker or release gate. Packaging has **not** been executed.
