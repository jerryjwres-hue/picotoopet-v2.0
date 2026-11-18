# PicotooPet auto-QC v1 (CPU). identity (DINOv2) + object counts (OWLv2 open-vocab) + camera lock (corner phase correlation)
# Usage: python qc_v1.py qc_jobs_v1.json
import sys, json, math, time
from pathlib import Path
import numpy as np, torch, av
from PIL import Image
from transformers import AutoImageProcessor, AutoModel, Owlv2Processor, Owlv2ForObjectDetection
HERE = Path(__file__).resolve().parent
cfg = json.loads((HERE / sys.argv[1]).read_text(encoding="utf-8"))
out_name = "qc_v1_report_" + Path(sys.argv[1]).stem
log = open(HERE / "qc_v1_log.txt", "a", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); log.write(s + "\n"); log.flush()
torch.set_num_threads(4)
P("=== qc v1 start", time.strftime("%H:%M:%S"), "torch", torch.__version__)
dproc = AutoImageProcessor.from_pretrained("facebook/dinov2-small"); dino = AutoModel.from_pretrained("facebook/dinov2-small").eval()
oproc = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble"); owl = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").eval()
QUERIES = ["a dog", "a human face", "a human hand", "a metal pet food bowl", "a plate of food"]
KEYS = ["dog", "face", "hand", "bowl", "plate"]
def emb(imgs):
    with torch.no_grad():
        o = dino(**dproc(images=imgs, return_tensors="pt")).last_hidden_state[:, 0]
    return torch.nn.functional.normalize(o, dim=-1)
def frames(p, fps=4):
    c = av.open(str(p)); s = c.streams.video[0]; out = []; nxt = 0.0
    for f in c.decode(s):
        t = float(f.pts * s.time_base)
        if t + 1e-6 >= nxt: out.append(f.to_image().convert("RGB")); nxt += 1.0 / fps
    c.close(); return out
def count(img, thr=0.3):
    with torch.no_grad():
        inp = oproc(text=[QUERIES], images=img, return_tensors="pt"); o = owl(**inp)
    W, H = img.size; side = max(W, H)
    pp = getattr(oproc, "post_process_grounded_object_detection", None) or oproc.post_process_object_detection
    res = pp(o, threshold=thr, target_sizes=torch.tensor([[side, side]]), text_labels=[QUERIES])[0]
    c = {k: 0 for k in KEYS}
    boxes = res["boxes"].tolist(); labs = res["labels"].tolist(); scs = res["scores"].tolist()
    def iou(a, b):
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); inter = ix * iy
        ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / ua if ua > 0 else 0
    def inside(a, b):  # a mostly inside b
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy / max(1e-6, (a[2] - a[0]) * (a[3] - a[1])) > 0.7
    kept = []
    for i in sorted(range(len(boxes)), key=lambda i: -scs[i]):
        if any(labs[j] == labs[i] and (iou(boxes[i], boxes[j]) > 0.4 or inside(boxes[i], boxes[j]) or inside(boxes[j], boxes[i])) for j in kept): continue
        kept.append(i)
    for i in kept: c[KEYS[labs[i]]] += 1
    return c
def corners(img):
    g = img.convert("L"); w, h = g.size; pw, ph = w // 5, h // 8; out = []
    for (x, y) in [(0, 0), (w - pw, 0), (0, h - ph), (w - pw, h - ph)]:
        a = np.asarray(g.crop((x, y, x + pw, y + ph)).resize((64, 64)), dtype=np.float32); out.append(a - a.mean())
    return out
def shift(a, b):
    R = np.fft.fft2(a) * np.conj(np.fft.fft2(b)); R /= np.abs(R) + 1e-8
    r = np.abs(np.fft.ifft2(R)); y, x = np.unravel_index(r.argmax(), r.shape); h, w = a.shape
    y = y - h if y > h // 2 else y; x = x - w if x > w // 2 else x
    return math.hypot(x / w, y / h) * 100
rows = []
for shot in cfg["shots"]:
    key = Image.open(shot["keyframe"]).convert("RGB"); ke = emb([key]); expect = shot.get("expect", {})
    for tp in shot["takes"]:
        fr = frames(tp); E = emb(fr)
        sim_key = (E @ ke.T).squeeze(1).numpy(); sim_adj = (E[1:] * E[:-1]).sum(1).numpy()
        c0 = corners(fr[0]); cam = float(np.median([max(shift(a, b) for b in [corners(f)[i] for f in fr[1:]]) for i, a in enumerate(c0)]))
        idx = sorted(set([0, len(fr) // 4, len(fr) // 2, 3 * len(fr) // 4, len(fr) - 1]))
        counts = [count(fr[i]) for i in idx]
        mx = {k: max(c[k] for c in counts) for k in KEYS}
        flags = []
        for k in KEYS:
            lim = expect.get(k, 0)
            if mx[k] > lim: flags.append(f"{k}>{lim}({mx[k]})")
        if cam > 6: flags.append(f"camera_moved({cam:.1f}%)")
        if sim_adj.min() < 0.9: flags.append(f"sudden_change({sim_adj.min():.2f})")
        score = float(sim_key.min()) * 0.5 + float(sim_adj.min()) * 0.5 - 0.1 * len(flags)
        r = {"shot": shot["id"], "take": Path(tp).name, "id_min": round(float(sim_key.min()), 3), "adj_min": round(float(sim_adj.min()), 3),
             "cam_pct": round(cam, 2), "max_counts": mx, "flags": flags, "score": round(score, 3)}
        rows.append(r); P(json.dumps(r, ensure_ascii=False))
rows.sort(key=lambda r: (r["shot"], -r["score"]))
(HERE / (out_name + ".json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
lines = ["shot,take,score,flags"] + [f'{r["shot"]},{r["take"]},{r["score"]},"{" ".join(r["flags"])}"' for r in rows]
(HERE / (out_name + ".csv")).write_text("\n".join(lines), encoding="utf-8-sig")
P("=== qc v1 done", time.strftime("%H:%M:%S"))
