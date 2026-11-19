"""Shared FFprobe command and result decoding for local media tools."""

import json


def probe_command(path, *, local_mp4=False):
    restrictions = ["-protocol_whitelist", "file,pipe", "-f", "mov"] if local_mp4 else []
    return [
        "ffprobe",
        "-v",
        "error",
        *restrictions,
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]


def probe_json(result):
    return json.loads(result.stdout) if result.returncode == 0 else {}
