"""Story Director instructions and bounded context for the opt-in v2 Creative runtime.

Everything the local model receives for the Video Bible stage is assembled here and in
``CreativeIntelligenceCoordinator._stage_context``: the system prompt below, the strict JSON
schema of ``VideoBibleDraft`` and a context object that carries only validated earlier stages,
the allowed evidence ids and the hard constraints. Source text stays untrusted data.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from picotoopet_core.production.profile import VIDEO_OUTPUT_PROFILES

from .models import CreativeBriefResult, CreativeScriptResult
from .video_bible import (
    CAMERA_PHRASE,
    MAX_BIBLE_SHOTS,
    MIN_SHOT_SECONDS,
    CameraMovement,
)

# Renderer ceiling: 121 frames at 24 fps (see production/profile.frame_count_for_duration).
MAX_SHOT_SECONDS = 5.0
MAX_DIRECTIVE_SHOTS = 12

VIDEO_BIBLE_TEMPLATE_VERSION = "video-bible-v1.0.0"
SHOT_PLAN_FROM_BIBLE_TEMPLATE_VERSION = "shot-plan-from-bible-v1.0.0"

STORY_DIRECTOR_INSTRUCTIONS = (
    " You are the Story Director. Return one video_bible.v1 object: the single source of "
    "truth for subject and product identity, scenes, camera and shot-to-shot continuity of a "
    "short product video that a local text-to-video model renders one shot at a time with no "
    "memory between shots. "
    "(1) Identity: write subject.identity_phrase and product.identity_phrase once, as concrete "
    "visible attributes (species or breed, coat colour, marks, accessories; shape, colour, "
    "material). They are copied word for word into every shot that features them. Never "
    "depend on a brand name, readable text or a logo. "
    "(2) Claims: invent no product facts. Every product.claims entry that is verified must "
    "cite ids from allowed_evidence_ids; creative-only statements get verified=false with no "
    "evidence and must never appear in a voiceover. "
    "(3) Shots: split the script beats into shots of "
    f"{MIN_SHOT_SECONDS:g} to 5.0 seconds (aim for 3 to 5) with exactly one dominant visible "
    "action each; never join actions with 'then' or semicolons. Cover every beat in order. "
    "Give each shot opening_state and closing_state; use handoff_to_next CONTINUOUS only when "
    "the next shot's opening_state is word for word this shot's closing_state. "
    "(4) arc lists exactly the supplied beat_ids in order; the first is HOOK and the last, the "
    "supplied CTA beat, is the only CTA. "
    "(5) Scenes: one environment phrase, one lighting phrase and at most six palette words per "
    "place; reuse a scene for shots that happen in the same place. "
    "(6) Camera: choose camera_movement only from camera_rules.allowed_movements and keep "
    "screen direction consistent. "
    "(7) Write phrases in concise English. Forbidden: URLs, file paths, image or video file "
    "names, reference images, tools, workflows, model or software instructions, and quality "
    "adjective spam such as 8K, masterpiece or cinematic. "
    "(8) If the evidence cannot support a coherent video, set needs_human to true instead of "
    "inventing facts."
)


@dataclass(frozen=True)
class GoalDirectives:
    """Hard, explicit asks found in the Goal objective. They can only tighten the gates."""

    shot_count: int | None = None
    text_to_video_only: bool = False
    shot_seconds: float | None = None


_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10,
}
_COUNT = re.compile(
    r"(?<![0-9a-z.])(?P<n>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|[一二两三四五六七八九十])\s*-?\s*(?:shots?\b|个镜头|個鏡頭|镜头|鏡頭)",
    re.IGNORECASE,
)
_BEFORE = (
    "at least", "at most", "up to", "no more than", "more than", "fewer than", "less than",
    "minimum", "maximum", "about", "around", "approximately", "至少", "最多", "不少于",
    "不超过", "不多于", "超过", "多于", "少于", "大约", "约",
)
_AFTER = ("以上", "以内", "左右", "or more", "or fewer", "or less", "+")
# "2 shots of espresso" / "flu shots" are drinks and injections, not camera shots.
_NOT_CAMERA_BEFORE = (
    "flu", "vaccin", "booster", "covid", "espresso", "coffee", "tequila", "vodka", "whisk",
    "insulin",
)
_NOT_CAMERA_AFTER = re.compile(
    r"^\s*(?:of\s+)?(?:espresso|coffee|tequila|vodka|whisk|rum\b|gin\b|sake|juice|vaccine|"
    r"insulin|booster)"
)
_NO_REFERENCE = (
    "no image-to-video", "no image to video", "no i2v", "without image-to-video",
    "without i2v", "no reference images", "no reference image", "without a reference image",
    "without reference image", "no reference", "不使用参考图", "不要参考图", "无参考图",
    "不用参考图", "无需参考图", "不使用图生视频", "不要图生视频", "不用图生视频", "不做图生视频",
)
_TEXT_ONLY = (
    "text-to-video only", "text to video only", "t2v only", "only text-to-video", "t2v",
    "仅文生视频", "只用文生视频", "纯文生视频", "文生视频",
)
_IMAGE_WORDS = ("i2v", "image-to-video", "image to video", "图生视频", "reference image", "参考图")
_NO_REFERENCE_PATTERN = re.compile(
    "|".join(re.escape(item) for item in sorted(_NO_REFERENCE, key=len, reverse=True))
)


_SECONDS = (
    re.compile(
        r"(?:each|every)\s+shot\s+(?:is\s+|lasts\s+|of\s+|at\s+)?"
        r"(?P<s>\d+(?:\.\d+)?)\s*(?:seconds?|secs?)\b"
    ),
    re.compile(r"(?P<s>\d+(?:\.\d+)?)\s*(?:seconds?|secs?)\s+(?:per|each)\s+shot"),
    re.compile(r"(?P<s>\d+(?:\.\d+)?)-second\s+shots?\b"),
    re.compile(r"每(?:个)?镜头\s*(?P<s>\d+(?:\.\d+)?)\s*秒"),
)
_SECONDS_RANGE = (2.0, 5.0)


def _requested_shot_seconds(text: str) -> float | None:
    values: set[float] = set()
    for pattern in _SECONDS:
        for match in pattern.finditer(text):
            before = text[max(0, match.start() - 16) : match.start()]
            after = text[match.end() : match.end() + 10]
            if any(token in before for token in _BEFORE) or any(t in after for t in _AFTER):
                continue
            values.add(float(match.group("s")))
    if len(values) != 1:
        return None
    value = next(iter(values))
    return value if _SECONDS_RANGE[0] <= value <= _SECONDS_RANGE[1] else None


def parse_goal_directives(objective: str | None) -> GoalDirectives:
    """Deterministically read an explicit shot count and a text-to-video-only ask."""

    if not objective:
        return GoalDirectives()
    text = objective.casefold()
    counts: set[int] = set()
    ambiguous = False
    for match in _COUNT.finditer(text):
        before = text[max(0, match.start() - 16) : match.start()]
        after = text[match.end() : match.end() + 10]
        if any(token in before for token in _BEFORE) or any(t in after for t in _AFTER):
            continue
        if any(token in text[max(0, match.start() - 24) : match.start()]
               for token in _NOT_CAMERA_BEFORE) or _NOT_CAMERA_AFTER.match(
                   text[match.end() : match.end() + 24]):
            continue
        raw = match.group("n")
        value = int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]
        if 1 <= value <= MAX_DIRECTIVE_SHOTS:
            counts.add(value)
        else:
            ambiguous = True  # a count outside the supported range is not a directive
    shot_count = next(iter(counts)) if len(counts) == 1 and not ambiguous else None
    negated = bool(_NO_REFERENCE_PATTERN.search(text))
    remaining = _NO_REFERENCE_PATTERN.sub(" ", text)
    wants_image = any(word in remaining for word in _IMAGE_WORDS)
    marked = negated or any(marker in remaining for marker in _TEXT_ONLY)
    return GoalDirectives(
        shot_count=shot_count,
        text_to_video_only=marked and not wants_image,
        shot_seconds=_requested_shot_seconds(text),
    )


_CJK = re.compile(r"[\u4e00-\u9fff]")
# Words the frozen Wan negative prompt (windows/production/workflows: 色调艳丽 过曝 静态
# 细节模糊不清 字幕 杂乱背景) tells the sampler to avoid; in the positive text they cancel
# themselves. Fixed-camera wording ("static camera", "静态镜头") and depth-of-field wording
# ("blurry background") describe the camera, not the picture quality the negative targets, so
# they stay allowed.
_CAMERA_NOUNS = (
    r"camera|cameras|shot|shots|frame|framing|tripod|angle|view|composition|lens|position|"
    r"mount|rig|wide|medium|close-up"
)
_NEGATIVE_WORDS = re.compile(
    r"\b(?P<en>overexposed|cluttered|subtitles?|captions?|garish|gaudy"
    rf"|static(?![\s-]+(?:{_CAMERA_NOUNS})\b)"
    r"|blurry(?!\s+(?:background|backdrop|foreground|bokeh|scenery)\b))\b"
    r"|(?P<zh>过曝|杂乱|字幕|色调艳丽|细节模糊|静态(?!镜头|机位|摄影|拍摄|构图|画幅))",
    re.IGNORECASE,
)
ACTION_SIMILARITY_LIMIT = 0.7


def _shingles(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.casefold()))
    han = _CJK.findall(text)
    return words | {han[i] + han[i + 1] for i in range(len(han) - 1)}


def near_duplicate_actions(actions: list[str]) -> tuple[int, int] | None:
    """First pair of shot actions that are the same sentence, or None.

    Words every shot shares (the pet, the place) are boilerplate and removed first, so a long
    common scene description cannot make two different verbs look alike, while two actions that
    differ by at most one word still count as duplicates.
    """

    sets = [_shingles(item) for item in actions]
    if len(sets) < 2:
        return None
    common = set.intersection(*sets)
    rest = [item - common for item in sets]
    for i, first in enumerate(rest):
        for j in range(i + 1, len(rest)):
            second = rest[j]
            union = first | second
            if not union:
                return (i, j)
            overlap = len(first & second) / len(union)
            contained = (first <= second or second <= first) and len(first ^ second) <= 1
            if overlap >= ACTION_SIMILARITY_LIMIT or contained:
                return (i, j)
    return None


def actions_too_similar(first: str, second: str) -> bool:
    return near_duplicate_actions([first, second]) is not None


def negative_conflicts(texts: list[str]) -> list[str]:
    """Words in positive text that the fixed negative prompt tells Wan to avoid."""

    found: list[str] = []
    for text in texts:
        for match in _NEGATIVE_WORDS.finditer(text):
            word = match.group(0).casefold()
            if word not in found:
                found.append(word)
    return found


_GENERIC_ANCHORS = frozenset({
    "video", "shot", "shots", "scene", "scenes", "camera", "same", "consistent", "consistency",
    "continuity", "anchor", "anchors", "style", "none", "null", "n/a", "na", "tbd", "todo",
    "unknown", "other", "item", "thing", "stuff", "subject", "product", "background",
    "foreground", "image", "picture", "frame",
})


def normalize_anchor(key: str) -> str:
    """NFKC, case, punctuation and spacing folded so equal anchors compare equal."""

    folded = unicodedata.normalize("NFKC", key).casefold()
    kept = "".join(
        " " if unicodedata.category(ch)[0] in {"P", "S", "Z", "C"} else ch for ch in folded
    )
    return " ".join(kept.split())


def is_meaningful_anchor(normalized: str) -> bool:
    """Reject placeholders: a shared 'a' / 'x1' / 'scene' carries no identity at all."""

    if not normalized or normalized in _GENERIC_ANCHORS:
        return False
    if all(word in _GENERIC_ANCHORS for word in normalized.split()):
        return False
    han = len(_CJK.findall(normalized))
    latin = sum(1 for ch in normalized if ch.isalpha() and not _CJK.match(ch))
    return han >= 2 or latin >= 3


def normalized_keys(keys: list[str]) -> set[str]:
    """The distinct, meaningful identity anchors in a list of continuity keys."""

    return {
        item for item in (normalize_anchor(key) for key in keys) if is_meaningful_anchor(item)
    }


def director_constraints(
    brief: CreativeBriefResult,
    script: CreativeScriptResult,
    directives: GoalDirectives | None = None,
) -> dict[str, Any]:
    spec = VIDEO_OUTPUT_PROFILES[brief.output_profile_id]
    constraints = {
        "output_profile_id": brief.output_profile_id.value,
        "frame_size": f"{spec.width}x{spec.height}",
        "shot_seconds": {"min": MIN_SHOT_SECONDS, "preferred": [3.0, 5.0], "max": 5.0},
        "max_shots": MAX_BIBLE_SHOTS,
        "script_beat_ids": [beat.beat_id for beat in script.beats],
        "cta_beat_id": script.cta_beat_id,
        "script_target_duration_seconds": script.target_duration_seconds,
        "camera_rules": {
            "allowed_movements": [movement.value for movement in CameraMovement],
            "phrases": {key.value: value for key, value in CAMERA_PHRASE.items()},
        },
        "reference_images": "none: no approved image exists; do not describe or request one",
    }
    if directives is not None and directives.shot_count is not None:
        constraints["required_shot_count"] = directives.shot_count
    if directives is not None and directives.text_to_video_only:
        constraints["text_to_video_only"] = True
    if directives is not None and directives.shot_seconds is not None:
        constraints["required_shot_seconds"] = directives.shot_seconds
    return constraints
