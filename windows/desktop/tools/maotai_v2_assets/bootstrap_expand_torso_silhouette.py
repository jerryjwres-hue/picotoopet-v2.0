from __future__ import annotations

from pathlib import Path

from PIL import Image


ASSET_ROOT = Path(__file__).resolve().parents[2] / "src" / "PicotooPet.Desktop" / "Assets" / "Maotai" / "V2"

# Target alpha bounds are intentionally fixed from the accepted visual-fit candidates.
# The operation only widens/repositions the existing torso art; it does not synthesize new pixels or touch rig math.
TARGETS: dict[str, tuple[int, int, int, int]] = {
    "torso_neutral.png": (8, 8, 176, 148),
    "torso_crouch.png": (6, 6, 186, 138),
    "torso_stretch.png": (15, 6, 165, 166),
}


def visible_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise RuntimeError("torso asset has no visible alpha pixels")
    return bbox


def remap_visible_bounds(path: Path, target: tuple[int, int, int, int]) -> bool:
    with Image.open(path) as source:
        image = source.convert("RGBA")

    current = visible_bbox(image)
    if current == target:
        print(f"UNCHANGED {path.name} bbox={current}")
        return False

    crop = image.crop(current)
    target_width = target[2] - target[0]
    target_height = target[3] - target[1]
    resized = crop.resize((target_width, target_height), Image.Resampling.LANCZOS)

    output = Image.new("RGBA", image.size, (0, 0, 0, 0))
    output.alpha_composite(resized, dest=(target[0], target[1]))

    actual = visible_bbox(output)
    if actual != target:
        raise RuntimeError(f"{path.name}: expected alpha bbox {target}, got {actual}")

    # Preserve a real RGBA PNG and enough transparent border for rotation/scale safety.
    output.save(path, format="PNG", optimize=True, compress_level=9)
    print(f"UPDATED {path.name} bbox={current} -> {actual}")
    return True


def main() -> int:
    changed = False
    for file_name, target in TARGETS.items():
        path = ASSET_ROOT / file_name
        if not path.is_file():
            raise FileNotFoundError(path)
        changed = remap_visible_bounds(path, target) or changed

    print("MAOTAI_TORSO_BOOTSTRAP=" + ("CHANGED" if changed else "NOOP"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
