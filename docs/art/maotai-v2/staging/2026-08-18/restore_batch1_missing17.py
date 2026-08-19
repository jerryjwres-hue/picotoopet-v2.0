#!/usr/bin/env python3
"""Restore the Maotai v2 2026-08-18 full missing-17 restart checkpoint."""
from __future__ import annotations
import base64
import struct
import sys
import zlib
from pathlib import Path
from PIL import Image

def restore(pack_path: Path, out_dir: Path) -> list[Path]:
    packed = pack_path.read_text(encoding="utf-8").strip()
    raw = memoryview(zlib.decompress(base64.b85decode(packed.encode("ascii"))))
    pos = 0
    if bytes(raw[:4]) != b"MTR1":
        raise RuntimeError("invalid MTR1 pack")
    pos = 4
    count = struct.unpack_from(">H", raw, pos)[0]
    pos += 2
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for _ in range(count):
        nlen = struct.unpack_from(">H", raw, pos)[0]; pos += 2
        name = bytes(raw[pos:pos+nlen]).decode("utf-8"); pos += nlen
        width, height, pcount = struct.unpack_from(">HHB", raw, pos); pos += 5
        plen = pcount * 4
        palette = bytes(raw[pos:pos+plen]); pos += plen
        ilen = struct.unpack_from(">I", raw, pos)[0]; pos += 4
        indices = bytes(raw[pos:pos+ilen]); pos += ilen
        if ilen != width * height:
            raise RuntimeError(f"bad index length for {name}")
        pal = [palette[i:i+4] for i in range(0, len(palette), 4)]
        rgba = bytearray(width * height * 4)
        for i, idx in enumerate(indices):
            rgba[i*4:i*4+4] = pal[idx]
        path = out_dir / name
        Image.frombytes("RGBA", (width, height), bytes(rgba)).save(path, "PNG")
        written.append(path)
    return written

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    pack = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "batch1_missing17.mtr.b85"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "batch1_restored"
    files = restore(pack, out)
    if len(files) != 17:
        raise SystemExit(f"expected 17 restored candidates, got {len(files)}")
    for path in files:
        print(path)
