# PicotooPet static keyframe board V2 - local FLUX.2 Klein 4B via a private ComfyUI on 127.0.0.1:8190.
# Usage: python run_flux_board.py jobs_stage1.json
import json, os, sys, time, shutil, subprocess, urllib.request
from pathlib import Path
HERE = Path(__file__).resolve().parent
COMFY = Path(r"D:\opc in D\AI\ComfyUI\ComfyUI")
PY = Path(r"D:\opc in D\AI\ComfyUI\standalone-env\python.exe")
PORT = 8190; BASE = f"http://127.0.0.1:{PORT}"
LOG = HERE / "run_log.txt"
def log(m):
    line = time.strftime("%H:%M:%S ") + m; print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")
def get(path, timeout=5):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r: return json.loads(r.read())
def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())
def vram_used():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip()
    u, t = [int(x) for x in out.split(",")]; return u, t
def build(job, seed, ref_names):
    W, H = job.get("w", 864), job.get("h", 1536)
    g = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-2-klein-4b-fp8.safetensors", "weight_dtype": "default"}},
         "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "flux2", "device": "default"}},
         "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
         "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": job["prompt"]}},
         "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}}}
    pos, neg = ["4", 0], ["5", 0]
    model_ref = ["1", 0]
    if job.get("lora"):
        g["6"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": job["lora"]["name"], "strength_model": job["lora"].get("strength", 1.0)}}
        model_ref = ["6", 0]
    for i, name in enumerate(ref_names):
        b = 100 + 10 * i
        g[str(b)] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g[str(b+1)] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [str(b), 0], "upscale_method": "nearest-exact", "megapixels": 1.0, "resolution_steps": 1}}
        g[str(b+2)] = {"class_type": "VAEEncode", "inputs": {"pixels": [str(b+1), 0], "vae": ["3", 0]}}
        g[str(b+3)] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [str(b+2), 0]}}
        g[str(b+4)] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg, "latent": [str(b+2), 0]}}
        pos, neg = [str(b+3), 0], [str(b+4), 0]
    g.update({"20": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
              "21": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": W, "height": H}},
              "22": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
              "23": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
              "24": {"class_type": "CFGGuider", "inputs": {"model": model_ref, "positive": pos, "negative": neg, "cfg": 1.0}},
              "25": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["23", 0], "guider": ["24", 0], "sampler": ["22", 0], "sigmas": ["21", 0], "latent_image": ["20", 0]}},
              "26": {"class_type": "VAEDecode", "inputs": {"samples": ["25", 0], "vae": ["3", 0]}},
              "27": {"class_type": "SaveImage", "inputs": {"images": ["26", 0], "filename_prefix": "PTV2_" + job["id"]}}})
    return g
def main():
    jobs_file = HERE / sys.argv[1]; spec = json.loads(jobs_file.read_text(encoding="utf-8"))
    outdir = HERE / spec["out"]; outdir.mkdir(exist_ok=True)
    log(f"=== start {jobs_file.name}")
    try:
        get("/system_stats", 2); log("STOP: port 8190 already in use; another ComfyUI is running."); return 2
    except Exception: pass
    u, t = vram_used(); log(f"VRAM used {u}/{t} MiB")
    if u > 5000: log("STOP: GPU busy (>5000 MiB used). Close LTX Desktop jobs / games and rerun."); return 3
    env = dict(os.environ, PYTHONPATH=str(COMFY / ".venv" / "Lib" / "site-packages"))
    proc = subprocess.Popen([str(PY), "main.py", "--listen", "127.0.0.1", "--port", str(PORT), "--disable-auto-launch", "--disable-api-nodes"],
                            cwd=str(COMFY), env=env, stdout=open(HERE / "comfyui_server.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try: get("/system_stats", 2); break
            except Exception: time.sleep(1)
        else: log("STOP: ComfyUI did not start in 120 s; see comfyui_server.log"); return 4
        log("ComfyUI up")
        inp = COMFY / "input"
        for job in spec["jobs"]:
            refs = []
            for r in job.get("refs", []):
                src = HERE / r; name = "PTV2_" + src.name; shutil.copyfile(src, inp / name); refs.append(name)
            for k, seed in enumerate(job["seeds"]):
                pid = post("/prompt", {"prompt": build(job, seed, refs)})["prompt_id"]
                t0 = time.time()
                while True:
                    h = get(f"/history/{pid}")
                    if pid in h: break
                    if time.time() - t0 > 600: log(f"STOP: {job['id']} timeout"); return 5
                    time.sleep(1)
                st = h[pid].get("status", {}).get("status_str")
                imgs = [im for o in h[pid].get("outputs", {}).values() for im in o.get("images", [])]
                if st != "success" or not imgs: log(f"FAIL {job['id']} seed {seed}: {st}"); continue
                im = imgs[0]; src = COMFY / "output" / im.get("subfolder", "") / im["filename"]
                dst = outdir / f"{job['id']}_v{k+1}.png"; shutil.copyfile(src, dst)
                log(f"OK {dst.name} seed={seed} {time.time()-t0:.1f}s")
        log("=== done"); return 0
    finally:
        proc.terminate()
        try: proc.wait(20)
        except Exception: proc.kill()
        log("ComfyUI stopped")
if __name__ == "__main__":
    sys.exit(main())
