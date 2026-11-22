"""Extract an exact ComfyUI API prompt graph from one existing PNG.

A PNG with an embedded prompt is evidence of embedded metadata, NOT evidence
of a recoverable Comfy prompt ID, successfully completed history, owner rights,
correct identity conditioning, or permission to execute the graph.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

from scripts.recover_comfy_keyframe_workflow import (
    IMAGE_SUFFIXES, MAX_INPUTS, MAX_NODES, MODEL_NAMES, SLOT_NAMES,
    canonical_bytes, parse_history,
)

MAX_PNG_BYTES = 32 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def recover_embedded_png(raw: bytes, source_name: str) -> tuple[bytes, dict]:
    """Fail closed on corrupt image framing, duplicate prompt or UI-only metadata."""
    if (not 0 < len(raw) <= MAX_PNG_BYTES or not raw.startswith(PNG_MAGIC)
        or not source_name.lower().endswith(".png")):
        raise ValueError("PNG_EVIDENCE_FILE_INVALID")
    cursor, seen_ihdr, seen_idat, seen_end, embedded, dimensions = 8, False, False, False, None, None
    while cursor < len(raw):
        if cursor + 12 > len(raw):
            raise ValueError("PNG_EVIDENCE_CHUNK_TRUNCATED")
        length = struct.unpack_from(">I", raw, cursor)[0]
        kind = raw[cursor + 4:cursor + 8]
        if length > MAX_PNG_BYTES or cursor + 12 + length > len(raw):
            raise ValueError("PNG_EVIDENCE_CHUNK_OVERFLOW")
        data = raw[cursor + 8:cursor + 8 + length]
        expected = struct.unpack_from(">I", raw, cursor + 8 + length)[0]
        if zlib.crc32(kind + data) & 0xffffffff != expected:
            raise ValueError("PNG_EVIDENCE_CRC_INVALID")
        if not seen_ihdr:
            if kind != b"IHDR" or length != 13:
                raise ValueError("PNG_EVIDENCE_IHDR_REQUIRED")
            width, height = struct.unpack_from(">II", data)
            if not 1 <= width <= 8192 or not 1 <= height <= 8192:
                raise ValueError("PNG_EVIDENCE_DIMENSIONS_INVALID")
            dimensions = [width, height]
            seen_ihdr = True
        elif kind in (b"IHDR", b"acTL", b"fcTL", b"fdAT"):
            raise ValueError("PNG_EVIDENCE_MULTIFRAME_INVALID")
        elif kind == b"IDAT":
            seen_idat = True
        elif kind == b"tEXt":
            separator = data.find(b"\x00")
            if separator < 0:
                raise ValueError("PNG_EVIDENCE_TEXT_INVALID")
            if data[:separator] == b"prompt":
                if embedded is not None or not seen_ihdr:
                    raise ValueError("PNG_EVIDENCE_PROMPT_DUPLICATED")
                # ComfyUI's tEXt prompt is a UTF-8 JSON API graph, not the
                # user-facing node layout stored separately as "workflow".
                embedded = data[separator + 1:]
        elif kind in (b"zTXt", b"iTXt"):
            # Unknown/compressed "prompt" cannot quietly replace a missing
            # exact API graph; only literal ComfyUI tEXt is accepted.
            if data.split(b"\x00", 1)[0] == b"prompt":
                raise ValueError("PNG_EVIDENCE_UNSUPPORTED_PROMPT_ENCODING")
        elif kind == b"IEND":
            if length != 0 or not seen_idat or cursor + 12 != len(raw):
                raise ValueError("PNG_EVIDENCE_END_INVALID")
            seen_end = True
        cursor += length + 12
        if seen_end:
            break
    if not seen_end or embedded is None or not embedded:
        raise ValueError("PNG_EVIDENCE_API_GRAPH_MISSING")
    graph = parse_history(embedded)
    if not 1 <= len(graph) <= MAX_NODES:
        raise ValueError("PNG_EVIDENCE_GRAPH_INVALID")
    inventory = []
    output_count = 0
    for node_id, node in sorted(graph.items()):
        if (not isinstance(node_id, str) or not 1 <= len(node_id) <= 128
            or not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
            or not 1 <= len(node["class_type"]) <= 160
            or not isinstance(node.get("inputs"), dict)
            or len(node["inputs"]) > MAX_INPUTS):
            raise ValueError("PNG_EVIDENCE_NODE_INVALID")
        inputs = node["inputs"]
        if node["class_type"] == "SaveImage" and isinstance(inputs.get("filename_prefix"), str):
            output_count += 1
        inventory.append({
            "node_id": node_id,
            "class_type": node["class_type"],
            "candidate_input_slots": sorted(k for k in inputs if k in SLOT_NAMES),
            "declared_model_selectors": {
                k: v for k, v in inputs.items() if k in MODEL_NAMES
                and isinstance(v, str) and 1 <= len(v) <= 512
            },
        })
    if output_count < 1:
        raise ValueError("PNG_EVIDENCE_SAVEIMAGE_MISSING")
    graph_bytes = canonical_bytes(graph)
    return graph_bytes, {
        "schema": "picotoo.local-keyframe-workflow-recovery.v1",
        "prompt_id": None,
        "graph_sha256": hashlib.sha256(graph_bytes).hexdigest(),
        "graph_file": "workflow_api.json",
        "node_count": len(graph),
        "historical_image_output_count": None,
        "node_inventory": inventory,
        "history_status": "PNG_EMBEDDED_NO_HISTORY",
        "source_kind": "COMFY_PNG_TEXt_PROMPT",
        "source_image_sha256": hashlib.sha256(raw).hexdigest(),
        "source_image_bytes": len(raw),
        "source_image_dimensions": dimensions,
        "source_image_container_crc_verified": True,
        "image_pixels_decoded": False,
        "image_bytes_verified": True,
        "model_bytes_verified": False,
        "binding_reviewed": False,
        "workflow_registered": False,
        "production_authorized": False,
        "gpu_post": 0,
        "next_state": "UNTRUSTED_GRAPH_NO_HISTORY_REQUIRES_LOCAL_BINDING_REVIEW",
    }


def recover_png_file(path: Path) -> tuple[bytes, dict]:
    """Read bounded local bytes; never search neighboring files or contact Comfy."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_PNG_BYTES + 1)
    return recover_embedded_png(raw, path.name)
