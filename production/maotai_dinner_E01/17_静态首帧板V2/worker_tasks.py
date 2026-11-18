# Task logic for studio_worker.py (hot-reloaded per task). Runs scripts that live in this folder only.
import json, subprocess, time
from pathlib import Path
HERE = Path(__file__).resolve().parent; ROOT = HERE.parent; Q = ROOT / "_queue"
PY = Path(r"D:\opc in D\AI\ComfyUI\standalone-env\python.exe"); SP = Path(r"D:\opc in D\AI\ComfyUI\ComfyUI\.venv\Lib\site-packages")
def outputs_of(jobs_path):
    try: spec = json.loads(jobs_path.read_text(encoding="utf-8"))
    except Exception: return []
    out = (HERE / spec.get("out", ".")).resolve(); files = []
    for j in spec.get("jobs", []):
        for k in range(len(j.get("seeds", [0]))):
            for ext in (".png", ".mp4"):
                p = out / f"{j['id']}_v{k+1}{ext}"
                if p.exists(): files.append(p)
    return files
def contact_sheet(files, dst, log):
    try:
        import sys; sys.path.insert(0, str(SP)); from PIL import Image, ImageDraw
        thumbs = []
        for f in files[:40]:
            if f.suffix == ".png": im = Image.open(f).convert("RGB")
            else:
                import av
                c = av.open(str(f)); frames = [fr.to_image() for fr in c.decode(video=0)]; c.close()
                pick = [frames[0], frames[len(frames)//2], frames[-1]]; w, h = pick[0].size
                im = Image.new("RGB", (w*3, h)); [im.paste(p, (i*w, 0)) for i, p in enumerate(pick)]
            im.thumbnail((540 if f.suffix == ".mp4" else 220, 400)); ImageDraw.Draw(im).text((4, 4), f.stem, fill=(255, 40, 40)); thumbs.append(im)
        if not thumbs: return None
        cols = 4 if files[0].suffix == ".png" else 2
        W = max(t.width for t in thumbs); H = max(t.height for t in thumbs); rows = (len(thumbs)+cols-1)//cols
        sheet = Image.new("RGB", (cols*W, rows*H), (16, 16, 16))
        for i, t in enumerate(thumbs): sheet.paste(t, ((i % cols)*W, (i//cols)*H))
        sheet.save(dst, quality=82); return dst
    except Exception as e:
        log(f"sheet error {e}"); return None
def run_task(tf, log):
    t = json.loads(tf.read_text(encoding="utf-8")); name = tf.stem; t0 = time.time()
    runner = t.get("runner"); res = {"task": name, "runner": runner, "note": t.get("note", ""), "started": time.strftime("%H:%M:%S")}
    if runner == "selftest": res.update(ok=True, seconds=0); return res
    script = (HERE / runner).resolve()
    if script.parent != HERE or script.suffix != ".py" or not script.exists(): raise ValueError(f"runner must be a .py in {HERE}: {runner}")
    args = list(t.get("args", []))
    if t.get("jobs"): args = [t["jobs"]] + args
    env = dict(__import__("os").environ, PYTHONPATH=str(SP))
    r = subprocess.run([str(PY), str(script)] + args, cwd=str(HERE), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    res.update(ok=(r.returncode == 0), returncode=r.returncode, seconds=round(time.time()-t0),
               tail=out[-1500:], fails=[l for l in out.splitlines() if any(k in l for k in ("FAIL", "STOP", "ERROR", "Traceback"))][-10:])
    if t.get("jobs"):
        files = outputs_of((HERE / t["jobs"]).resolve()); res["outputs"] = [str(f.relative_to(ROOT)) for f in files]
        sheet = contact_sheet(files, Q / "done" / f"{name}.sheet.jpg", log)
        if sheet: res["sheet"] = str(Path(sheet).relative_to(ROOT))
    return res
