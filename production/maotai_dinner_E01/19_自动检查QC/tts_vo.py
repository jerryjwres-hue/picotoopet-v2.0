# English VO for E01 with Kokoro-82M (Apache-2.0), CPU. Writes one wav per line + lines.json
import json, time
from pathlib import Path
import soundfile as sf
from kokoro import KPipeline
OUT = Path(__file__).resolve().parent.parent / "22_声音" / "vo"; OUT.mkdir(parents=True, exist_ok=True)
LINES = [("S1", "It's almost dinnertime."), ("S2", "Maotai knows that sound."), ("S3", "But there's still a little waiting."),
         ("S4", "Some things are worth getting up for."), ("S5", "One sleepy step at a time."),
         ("S6", "Finally. The first bite."), ("S7", "Worth every little step.")]
VOICES = ["am_michael", "af_heart"]
pipe = KPipeline(lang_code="a")
meta = []
for v in VOICES:
    for sid, text in LINES:
        t0 = time.time(); chunks = [a for _, _, a in pipe(text, voice=v, speed=0.95)]
        import numpy as np
        audio = np.concatenate([c.numpy() if hasattr(c, "numpy") else c for c in chunks])
        f = OUT / f"{v}_{sid}.wav"; sf.write(f, audio, 24000)
        meta.append({"voice": v, "shot": sid, "text": text, "file": f.name, "sec": round(len(audio) / 24000, 2)})
        print(v, sid, round(len(audio) / 24000, 2), "s", round(time.time() - t0, 1), "s gen", flush=True)
(OUT / "lines.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
print("TTS_DONE")
