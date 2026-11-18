# HunyuanVideo-Foley on a private ComfyUI: video in -> synced foley audio out (+ muxed mp4 and a separate audio file).
# job: {id, video, prompt, negative?, seeds:[...], steps?, cfg?}
import json, os, sys, time, shutil, subprocess, urllib.request, urllib.error
from pathlib import Path
HERE = Path(__file__).resolve().parent; C = Path(r"D:\opc in D\AI\ComfyUI"); CU = C / "ComfyUI"; PY = C / "standalone-env" / "python.exe"
PORT = 8190; BASE = f"http://127.0.0.1:{PORT}"; LOG = HERE / "run_log.txt"
def log(m):
    line = time.strftime("%H:%M:%S ") + m; print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")
def get(p, t=10):
    with urllib.request.urlopen(BASE + p, timeout=t) as r: return json.loads(r.read())
def post(p, o):
    req = urllib.request.Request(BASE + p, data=json.dumps(o).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: log("POST ERROR " + e.read().decode()[:3000]); raise
def duration(p):
    import av
    c = av.open(str(p)); d = float(c.duration / 1e6) if c.duration else 4.0; c.close(); return d
def build(job, seed, vname, dur):
    return {"1": {"class_type": "LoadVideo", "inputs": {"file": vname}},
            "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
            "3": {"class_type": "HunyuanModelLoader", "inputs": {"model_name": "hunyuanvideo_foley_fp8_e4m3fn.safetensors", "precision": "bf16", "quantization": "auto"}},
            "4": {"class_type": "HunyuanDependenciesLoader", "inputs": {"vae_name": "vae_128d_48k_fp16.safetensors", "synchformer_name": "synchformer_state_dict_fp16.safetensors"}},
            "5": {"class_type": "HunyuanFoleySampler", "inputs": {"hunyuan_model": ["3", 0], "hunyuan_deps": ["4", 0], "frame_rate": 24.0, "duration": round(dur, 2),
                  "prompt": job["prompt"], "negative_prompt": job.get("negative", "music, speech, talking, singing, noisy, harsh, distorted"),
                  "cfg_scale": job.get("cfg", 4.5), "steps": job.get("steps", 50), "sampler": "euler", "batch_size": 1, "seed": seed, "force_offload": True, "image": ["2", 0]}},
            "6": {"class_type": "CreateVideo", "inputs": {"images": ["2", 0], "fps": 24.0, "audio": ["5", 0]}},
            "7": {"class_type": "SaveVideo", "inputs": {"video": ["6", 0], "filename_prefix": "FOLEY_" + job["id"], "format": "auto", "codec": "auto"}},
            "8": {"class_type": "SaveAudio", "inputs": {"audio": ["5", 0], "filename_prefix": "FOLEY_" + job["id"]}}}
def main():
    spec = json.loads((HERE / sys.argv[1]).read_text(encoding="utf-8")); out = HERE / spec["out"]; out.mkdir(parents=True, exist_ok=True)
    log(f"=== start {sys.argv[1]} (foley)")
    try: get("/system_stats", 2); log("STOP: port busy"); return 2
    except Exception: pass
    env = dict(os.environ, PYTHONPATH=str(CU / ".venv" / "Lib" / "site-packages"))
    proc = subprocess.Popen([str(PY), "main.py", "--listen", "127.0.0.1", "--port", str(PORT), "--disable-auto-launch", "--disable-api-nodes"], cwd=str(CU), env=env,
                            stdout=open(HERE / "comfyui_server.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT)
    try:
        for _ in range(240):
            try: get("/system_stats", 2); break
            except Exception: time.sleep(1)
        else: log("STOP: no start"); return 4
        log("ComfyUI up"); OI = get("/object_info", 60)
        miss = [k for k in ("LoadVideo", "GetVideoComponents", "HunyuanFoleySampler", "SaveAudio") if k not in OI]
        if miss: log(f"STOP: missing nodes {miss}"); return 6
        inp = CU / "input"; ok = 0
        for job in spec["jobs"]:
            v = (HERE / job["video"]).resolve(); vn = "FO_" + v.name; shutil.copyfile(v, inp / vn); dur = duration(v)
            for k, seed in enumerate(job["seeds"]):
                pid = post("/prompt", {"prompt": build(job, seed, vn, dur)})["prompt_id"]; t0 = time.time()
                while True:
                    h = get(f"/history/{pid}", 30)
                    if pid in h: break
                    if time.time() - t0 > 1800: log("STOP timeout"); return 5
                    time.sleep(3)
                st = h[pid].get("status", {}); outs = h[pid].get("outputs", {})
                allx = [x for o in outs.values() for v in o.values() if isinstance(v, list) for x in v if isinstance(x, dict) and "filename" in x and x.get("type") == "output"]
                log("outputs: " + json.dumps(outs)[:600])
                vids = [x for x in allx if x["filename"].lower().endswith((".mp4", ".webm", ".mov"))]
                auds = [x for x in allx if x["filename"].lower().endswith((".flac", ".wav", ".mp3", ".opus"))]
                if st.get("status_str") != "success" or not vids: log(f"FAIL {job['id']} {json.dumps(st)[:1500]}"); continue
                for x, ext in ((vids[0], ".mp4"), (auds[0] if auds else None, ".flac")):
                    if not x: continue
                    src = CU / "output" / x.get("subfolder", "") / x["filename"]; dst = out / f"{job['id']}_v{k+1}{src.suffix or ext}"; shutil.copyfile(src, dst)
                ok += 1; log(f"OK {job['id']}_v{k+1} seed={seed} {time.time()-t0:.0f}s")
        log("=== done"); return 0 if ok else 7
    finally:
        proc.terminate()
        try: proc.wait(30)
        except Exception: proc.kill()
        log("ComfyUI stopped")
if __name__ == "__main__":
    try: sys.exit(main())
    except Exception:
        import traceback; log("CRASH " + traceback.format_exc()[-1500:]); sys.exit(9)
