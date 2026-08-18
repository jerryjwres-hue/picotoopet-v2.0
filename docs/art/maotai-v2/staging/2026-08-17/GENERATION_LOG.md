# Maotai v2 art generation log

- 2026-08-17: image generation attempt after Canva single-layer resize was cancelled.
- Generation id: `89bf9df4-8313-41cc-bfb4-615e7a5b8e60`.
- Result: rejected as a formal runtime asset because the generator returned a full multi-part atlas with extra props and completed poses instead of a single torso-only sprite.
- Action: preserve only a reduced preview in staging for continuity; do not crop it into `Assets/Maotai/V2`.
- Formal blocker remains `torso_neutral.png`.
