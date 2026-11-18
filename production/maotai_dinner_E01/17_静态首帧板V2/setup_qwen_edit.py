# Download Qwen-Image-Edit-2511 (FP8) + Lightning 4-step LoRA + multi-angle LoRA into the local ComfyUI. Official HF repos, safetensors only.
import os, sys, time, shutil, urllib.request
from pathlib import Path
HERE = Path(__file__).resolve().parent
COMFY = Path(r"D:\opc in D\AI\ComfyUI\ComfyUI")
LOG = HERE / "setup_qwen_log.txt"
def log(m):
    line = time.strftime("%H:%M:%S ") + m; print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")
HF = "https://huggingface.co/"
FILES = [
 ("diffusion_models", "qwen_image_edit_2511_fp8mixed.safetensors", ["Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors"]),
 ("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors", ["Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
                                                            "Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"]),
 ("vae", "qwen_image_vae.safetensors", ["Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"]),
 ("loras", "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", ["lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"]),
 ("loras", "qwen-image-edit-2511-multiple-angles-lora.safetensors", ["fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA/resolve/main/qwen-image-edit-2511-multiple-angles-lora.safetensors"]),
]
def fetch(url, dst):
    part = dst.with_suffix(dst.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0)) + have
        mode = "ab" if (have and r.status == 206) else "wb"
        if mode == "wb": have = 0
        t0 = time.time(); last = 0; done = have
        with open(part, mode) as f:
            while True:
                b = r.read(8 << 20)
                if not b: break
                f.write(b); done += len(b)
                if time.time() - last > 15:
                    last = time.time(); sp = (done - have) / max(1, time.time() - t0) / 1e6
                    log(f"  {dst.name}: {done/1e9:.2f}/{total/1e9:.2f} GB  {sp:.0f} MB/s")
    if total and part.stat().st_size < total: raise IOError("incomplete")
    part.replace(dst)
def main():
    log("=== setup start")
    try: log("ComfyUI version: " + (COMFY / "comfyui_version.py").read_text().strip().splitlines()[-1])
    except Exception as e: log(f"version? {e}")
    du = shutil.disk_usage(COMFY); log(f"D: free {du.free/1e9:.0f} GB")
    for sub in ("diffusion_models", "unet", "text_encoders", "clip", "vae", "loras"):
        d = COMFY / "models" / sub
        if d.exists(): log(f"[{sub}] " + ", ".join(sorted(p.name for p in d.iterdir() if p.is_file()))[:600])
    if du.free < 40e9: log("STOP: need ~35 GB free"); return 2
    for sub, name, urls in FILES:
        dst = COMFY / "models" / sub / name; dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.stat().st_size > 1e6: log(f"have {name}"); continue
        for u in urls:
            for attempt in range(4):
                try: log(f"get {name} <- {u.split('/')[0]}/{u.split('/')[1]}"); fetch(HF + u, dst); log(f"OK {name} {dst.stat().st_size/1e9:.2f} GB"); break
                except Exception as e: log(f"  retry {attempt}: {e}"); time.sleep(5)
            if dst.exists(): break
        if not dst.exists(): log(f"FAIL {name}"); return 3
    log("=== setup done"); return 0
if __name__ == "__main__": sys.exit(main())
