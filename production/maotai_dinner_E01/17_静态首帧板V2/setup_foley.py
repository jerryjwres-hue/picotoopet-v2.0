# Install HunyuanVideo-Foley ComfyUI nodes (phazei, pinned commit) + fp8/fp16 safetensors weights. Reviewed 2026-11-18.
import os, sys, time, shutil, subprocess, urllib.request
from pathlib import Path
CU = Path(r"D:\opc in D\AI\ComfyUI\ComfyUI"); NODE = CU / "custom_nodes" / "ComfyUI-HunyuanVideo-Foley"; COMMIT = "afd2960"
def log(m): print(time.strftime("%H:%M:%S ") + m, flush=True)
def run(cmd, **kw):
    log("$ " + " ".join(map(str, cmd))); r = subprocess.run(cmd, capture_output=True, text=True, **kw); log((r.stdout[-1500:] + r.stderr[-1500:]).strip()); return r.returncode
if not NODE.exists():
    if run(["git", "clone", "https://github.com/phazei/ComfyUI-HunyuanVideo-Foley", str(NODE)]): sys.exit(2)
run(["git", "-C", str(NODE), "fetch", "--depth", "50", "origin"]); 
if run(["git", "-C", str(NODE), "checkout", COMMIT]): log("WARN: pinned commit not found, staying on default branch")
(CU / "_pin_torch.txt").write_text("torch==2.10.0+cu130\ntorchvision==0.25.0+cu130\ntorchaudio==2.10.0+cu130\n")
shutil.copy(NODE / "requirements.txt", CU / "_foley_req.txt")
uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
if run([uv, "pip", "install", "--python", r"..\standalone-env\python.exe", "--target", r".venv\Lib\site-packages", "-r", "_foley_req.txt", "-c", "_pin_torch.txt",
        "--extra-index-url", "https://download.pytorch.org/whl/cu130", "--index-strategy", "unsafe-best-match"], cwd=str(CU)): sys.exit(3)
M = CU / "models" / "foley"; M.mkdir(parents=True, exist_ok=True)
for fn in ("hunyuanvideo_foley_fp8_e4m3fn.safetensors", "synchformer_state_dict_fp16.safetensors", "vae_128d_48k_fp16.safetensors"):
    dst = M / fn
    if dst.exists() and dst.stat().st_size > 1e6: log("have " + fn); continue
    url = "https://huggingface.co/phazei/HunyuanVideo-Foley/resolve/main/" + fn; part = dst.with_suffix(".part"); log("get " + url)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r, open(part, "wb") as f:
        while True:
            b = r.read(8 << 20)
            if not b: break
            f.write(b)
    part.replace(dst); log(f"OK {fn} {dst.stat().st_size/1e9:.2f} GB")
log("SETUP_DONE")
