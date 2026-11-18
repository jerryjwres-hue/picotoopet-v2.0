# PicotooPet auto-QC v0 (CPU only). Usage: python qc_v0.py qc_jobs_S2.json
import sys, json, math, time
from pathlib import Path
import numpy as np, torch, av
from transformers import AutoImageProcessor, AutoModel
HERE = Path(__file__).resolve().parent
cfg = json.loads((HERE / sys.argv[1]).read_text(encoding="utf-8"))
log = open(HERE / "qc_log.txt", "a", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); log.write(s + "\n"); log.flush()
P("=== qc start", time.strftime("%H:%M:%S"), "torch", torch.__version__)
torch.set_num_threads(4)
proc = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
model = AutoModel.from_pretrained("facebook/dinov2-small").eval()
def emb(imgs):
    with torch.no_grad():
        o = model(**proc(images=imgs, return_tensors="pt")).last_hidden_state[:, 0]
    return torch.nn.functional.normalize(o, dim=-1)
def frames(p, fps=4):
    c = av.open(str(p)); s = c.streams.video[0]; out = []; nxt = 0.0
    for f in c.decode(s):
        t = float(f.pts * s.time_base)
        if t + 1e-6 >= nxt: out.append(f.to_image().convert("RGB")); nxt += 1.0 / fps
    c.close(); return out
def strip(img):  # top 25% of frame = wall/background, grayscale 128 wide
    w, h = img.size; g = img.crop((0, 0, w, h // 4)).convert("L").resize((128, 32))
    a = np.asarray(g, dtype=np.float32); return a - a.mean()
def shift(a, b):
    R = np.fft.fft2(a) * np.conj(np.fft.fft2(b)); R /= np.abs(R) + 1e-8
    r = np.abs(np.fft.ifft2(R)); y, x = np.unravel_index(r.argmax(), r.shape); h, w = a.shape
    y = y - h if y > h // 2 else y; x = x - w if x > w // 2 else x
    return math.hypot(x / w, y / h) * 100  # percent of frame
rows = []
for shot in cfg["shots"]:
    from PIL import Image
    key = Image.open(shot["keyframe"]).convert("RGB")
    ke = emb([key])
    for tp in shot["takes"]:
        fr = frames(tp); E = emb(fr)
        sim_key = (E @ ke.T).squeeze(1).numpy()
        sim_adj = (E[1:] * E[:-1]).sum(1).numpy()
        strips = [strip(f) for f in fr]
        cam = max(shift(strips[0], s) for s in strips[1:])
        lum = np.array([np.asarray(f.convert("L"), dtype=np.float32).mean() for f in fr])
        flick = float(np.abs(np.diff(lum)).mean())
        r = {"shot": shot["id"], "take": Path(tp).name, "frames": len(fr),
             "id_min": round(float(sim_key.min()), 3), "id_end": round(float(sim_key[-1]), 3),
             "adj_min": round(float(sim_adj.min()), 3), "cam_shift_pct": round(cam, 2), "flicker": round(flick, 2)}
        r["score"] = round(r["id_min"] * 0.6 + r["adj_min"] * 0.4 - (0.05 if cam > 3 else 0) - 0.01 * max(0, flick - 2), 3)
        rows.append(r); P(json.dumps(r, ensure_ascii=False))
rows.sort(key=lambda r: (r["shot"], -r["score"]))
(HERE / ("qc_report_" + Path(sys.argv[1]).stem + ".json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
P("=== qc done", time.strftime("%H:%M:%S"))
