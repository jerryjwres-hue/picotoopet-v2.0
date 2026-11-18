# Qwen-Image-Edit-2511 (FP8 + Lightning 4-step) runner on a private ComfyUI at 127.0.0.1:8190. Same jobs format as run_flux_board.py.
# job: {id, refs:[...], seeds:[...], prompt, loras:[{name,strength}], steps}
import json, os, sys, time, shutil, subprocess, urllib.request
from pathlib import Path
HERE = Path(__file__).resolve().parent
COMFY = Path(r"D:\opc in D\AI\ComfyUI\ComfyUI")
PY = Path(r"D:\opc in D\AI\ComfyUI\standalone-env\python.exe")
PORT = 8190; BASE = f"http://127.0.0.1:{PORT}"
LOG = HERE / "run_log.txt"
LIGHT = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
def log(m):
    line = time.strftime("%H:%M:%S ") + m; print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")
def get(path, timeout=5):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r: return json.loads(r.read())
def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: log("POST ERROR " + e.read().decode()[:1500]); raise
def vram_used():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip()
    u, t = [int(x) for x in out.split(",")]; return u, t
def build(job, seed, refs, OI):
    g = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_2511_fp8mixed.safetensors", "weight_dtype": "default"}},
         "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
         "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}}}
    m = ["1", 0]
    loras = [{"name": LIGHT, "strength": 1.0}] + job.get("loras", [])
    for i, L in enumerate(loras):
        k = str(40 + i); g[k] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": m, "lora_name": L["name"], "strength_model": L.get("strength", 1.0)}}; m = [k, 0]
    g["50"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": m, "shift": 3.1}}; m = ["50", 0]
    if "CFGNorm" in OI: g["51"] = {"class_type": "CFGNorm", "inputs": {"model": m, "strength": 1.0}}; m = ["51", 0]
    imgs = {}
    for i, name in enumerate(refs[:3]):
        b = 100 + 10 * i
        g[str(b)] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g[str(b+1)] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [str(b), 0], "upscale_method": "lanczos", "megapixels": job.get("mp", 1.0), "resolution_steps": 8}}
        imgs[f"image{i+1}"] = [str(b+1), 0]
    g["4"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["2", 0], "prompt": job["prompt"], "vae": ["3", 0], **imgs}}
    g["5"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["2", 0], "prompt": job.get("negative", ""), "vae": ["3", 0], **imgs}}
    pos, neg = ["4", 0], ["5", 0]
    if "FluxKontextMultiReferenceLatentMethod" in OI:
        g["6"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": pos, "reference_latents_method": "index_timestep_zero"}}
        g["7"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": neg, "reference_latents_method": "index_timestep_zero"}}
        pos, neg = ["6", 0], ["7", 0]
    g["20"] = {"class_type": "VAEEncode", "inputs": {"pixels": imgs["image1"], "vae": ["3", 0]}}
    g["25"] = {"class_type": "KSampler", "inputs": {"model": m, "seed": seed, "steps": job.get("steps", 4), "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                                                    "positive": pos, "negative": neg, "latent_image": ["20", 0], "denoise": 1.0}}
    g["26"] = {"class_type": "VAEDecode", "inputs": {"samples": ["25", 0], "vae": ["3", 0]}}
    g["27"] = {"class_type": "SaveImage", "inputs": {"images": ["26", 0], "filename_prefix": "QE_" + job["id"]}}
    return g
def main():
    jobs_file = HERE / sys.argv[1]; spec = json.loads(jobs_file.read_text(encoding="utf-8"))
    outdir = (HERE / spec["out"]); outdir.mkdir(parents=True, exist_ok=True)
    log(f"=== start {jobs_file.name} (qwen-edit)")
    try:
        get("/system_stats", 2); log("STOP: port 8190 already in use"); return 2
    except Exception: pass
    u, t = vram_used(); log(f"VRAM used {u}/{t} MiB")
    if u > 5000: log("STOP: GPU busy (>5000 MiB used). Close LTX Desktop / games and rerun."); return 3
    env = dict(os.environ, PYTHONPATH=str(COMFY / ".venv" / "Lib" / "site-packages"))
    proc = subprocess.Popen([str(PY), "main.py", "--listen", "127.0.0.1", "--port", str(PORT), "--disable-auto-launch", "--disable-api-nodes"],
                            cwd=str(COMFY), env=env, stdout=open(HERE / "comfyui_server.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT)
    try:
        for _ in range(180):
            try: get("/system_stats", 2); break
            except Exception: time.sleep(1)
        else: log("STOP: ComfyUI did not start"); return 4
        OI = get("/object_info", 60); log("ComfyUI up; QwenEditPlus=%s CFGNorm=%s KontextMethod=%s" % ("TextEncodeQwenImageEditPlus" in OI, "CFGNorm" in OI, "FluxKontextMultiReferenceLatentMethod" in OI))
        if "TextEncodeQwenImageEditPlus" not in OI: log("STOP: ComfyUI too old for Qwen-Image-Edit-2511 (update ComfyUI)"); return 6
        inp = COMFY / "input"
        for job in spec["jobs"]:
            refs = []
            for r in job["refs"]:
                src = (HERE / r).resolve(); name = "QE_" + src.name; shutil.copyfile(src, inp / name); refs.append(name)
            for k, seed in enumerate(job["seeds"]):
                pid = post("/prompt", {"prompt": build(job, seed, refs, OI)})["prompt_id"]; t0 = time.time()
                while True:
                    h = get(f"/history/{pid}")
                    if pid in h: break
                    if time.time() - t0 > 900: log(f"STOP: {job['id']} timeout"); return 5
                    time.sleep(2)
                st = h[pid].get("status", {})
                imgs = [im for o in h[pid].get("outputs", {}).values() for im in o.get("images", [])]
                if st.get("status_str") != "success" or not imgs: log(f"FAIL {job['id']} seed {seed}: {json.dumps(st)[:800]}"); continue
                im = imgs[0]; src = COMFY / "output" / im.get("subfolder", "") / im["filename"]
                dst = outdir / f"{job['id']}_v{k+1}.png"; shutil.copyfile(src, dst)
                log(f"OK {dst.name} seed={seed} {time.time()-t0:.1f}s")
        log("=== done"); return 0
    finally:
        proc.terminate()
        try: proc.wait(20)
        except Exception: proc.kill()
        log("ComfyUI stopped")
if __name__ == "__main__": sys.exit(main())
