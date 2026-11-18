# LTX-2.5 (distilled, local ComfyUI) image->video with optional LAST frame (FLF). Mirrors the official video_ltx2_5_flf2v template, prompt-enhancer OFF.
# job: {id, first, last?, prompt, negative?, seconds(3|4|5), w, h, seeds:[...], fps?, guide_strength?, dtype?}
import json, os, sys, time, shutil, subprocess, urllib.request, urllib.error
from pathlib import Path
HERE=Path(__file__).resolve().parent; C=Path(r"D:\opc in D\AI\ComfyUI"); CU=C/"ComfyUI"; PY=C/"standalone-env"/"python.exe"
PORT=8190; BASE=f"http://127.0.0.1:{PORT}"; LOG=HERE/"run_log.txt"
NEG=("blurry, out of focus, low quality, flicker, jittery motion, morphing, melting, distorted anatomy, extra legs, extra tail, extra ears, deformed paws, "
     "warped face, long snout, duplicate dog, sudden cuts, camera shake, text, watermark, people, human face")
SIGMAS="1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
def log(m):
    line=time.strftime("%H:%M:%S ")+m; print(line,flush=True)
    with open(LOG,"a",encoding="utf-8") as f: f.write(line+"\n")
def get(p,t=10):
    with urllib.request.urlopen(BASE+p,timeout=t) as r: return json.loads(r.read())
def post(p,o):
    req=urllib.request.Request(BASE+p,data=json.dumps(o).encode(),headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=60) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: log("POST ERROR "+e.read().decode()[:3000]); raise
def vram():
    o=subprocess.run(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],capture_output=True,text=True).stdout.strip(); return int(o)
def build(job,seed,first,last):
    fps=job.get("fps",24); frames=int(job.get("seconds",4)*fps)//8*8+1; W,H=job["w"],job["h"]; gs=job.get("guide_strength",0.7)
    g={"1":{"class_type":"UNETLoader","inputs":{"unet_name":"ltx-2.5-22b-distilled-transformer-bf16.safetensors","weight_dtype":job.get("dtype","fp8_e4m3fn")}},
       "2":{"class_type":"CLIPLoader","inputs":{"clip_name":"gemma4-12b-with-proj-ltx-2.5-bf16.safetensors","type":"ltxv","device":"default"}},
       "3":{"class_type":"VAELoader","inputs":{"vae_name":"ltx-2.5-video-vae-bf16.safetensors"}},
       "4":{"class_type":"VAELoader","inputs":{"vae_name":"ltx-2.5-audio-vae-bf16.safetensors"}},
       "5":{"class_type":"CLIPTextEncode","inputs":{"clip":["2",0],"text":job["prompt"]}},
       "6":{"class_type":"CLIPTextEncode","inputs":{"clip":["2",0],"text":job.get("negative",NEG)}},
       "7":{"class_type":"LTXVConditioning","inputs":{"positive":["5",0],"negative":["6",0],"frame_rate":float(fps)}},
       "8":{"class_type":"EmptyLTXVLatentVideo","inputs":{"width":W,"height":H,"length":frames,"batch_size":1}},
       "10":{"class_type":"LoadImage","inputs":{"image":first}},
       "11":{"class_type":"ImageScale","inputs":{"image":["10",0],"upscale_method":"lanczos","width":W,"height":H,"crop":"center"}},
       "12":{"class_type":"LTXVPreprocess","inputs":{"image":["11",0],"img_compression":18}},
       "13":{"class_type":"LTXVAddGuide","inputs":{"positive":["7",0],"negative":["7",1],"vae":["3",0],"latent":["8",0],"image":["12",0],"frame_idx":0,"strength":gs}}}
    p,n,lat=["13",0],["13",1],["13",2]
    if last:
        g.update({"20":{"class_type":"LoadImage","inputs":{"image":last}},
                  "21":{"class_type":"ImageScale","inputs":{"image":["20",0],"upscale_method":"lanczos","width":W,"height":H,"crop":"center"}},
                  "22":{"class_type":"LTXVPreprocess","inputs":{"image":["21",0],"img_compression":18}},
                  "23":{"class_type":"LTXVAddGuide","inputs":{"positive":p,"negative":n,"vae":["3",0],"latent":lat,"image":["22",0],"frame_idx":-1,"strength":job.get("last_strength",gs)}}})
        p,n,lat=["23",0],["23",1],["23",2]
    g.update({"30":{"class_type":"LTXVEmptyLatentAudio","inputs":{"frames_number":frames,"frame_rate":fps,"batch_size":1,"audio_vae":["4",0]}},
              "31":{"class_type":"LTXVConcatAVLatent","inputs":{"video_latent":lat,"audio_latent":["30",0]}},
              "32":{"class_type":"LTXVDualCFGGuider","inputs":{"model":["1",0],"positive":p,"negative":n,"video_cfg":1.0,"audio_cfg":1.0}},
              "33":{"class_type":"RandomNoise","inputs":{"noise_seed":seed}},
              "34":{"class_type":"SamplerEulerAncestral","inputs":{"eta":0.0,"s_noise":1.0}},
              "35":{"class_type":"ManualSigmas","inputs":{"sigmas":SIGMAS}},
              "36":{"class_type":"SamplerCustomAdvanced","inputs":{"noise":["33",0],"guider":["32",0],"sampler":["34",0],"sigmas":["35",0],"latent_image":["31",0]}},
              "37":{"class_type":"LTXVSeparateAVLatent","inputs":{"av_latent":["36",1]}},
              "38":{"class_type":"LTXVCropGuides","inputs":{"positive":p,"negative":n,"latent":["37",0]}},
              "39":{"class_type":"VAEDecodeTiled","inputs":{"samples":["38",2],"vae":["3",0],"tile_size":512,"overlap":64,"temporal_size":64,"temporal_overlap":16}},
              "40":{"class_type":"LTXVAudioVAEDecode","inputs":{"samples":["37",1],"audio_vae":["4",0]}},
              "41":{"class_type":"CreateVideo","inputs":{"images":["39",0],"fps":float(fps),"audio":["40",0]}},
              "42":{"class_type":"SaveVideo","inputs":{"video":["41",0],"filename_prefix":"LTXF_"+job["id"],"format":"auto","codec":"auto"}}})
    return g
def main():
    spec=json.loads((HERE/sys.argv[1]).read_text(encoding="utf-8")); out=HERE/spec["out"]; out.mkdir(parents=True,exist_ok=True)
    log(f"=== start {sys.argv[1]} (ltx-2.5)")
    try: get("/system_stats",2); log("STOP: port busy"); return 2
    except Exception: pass
    if vram()>5000: log("STOP: GPU busy (close LTX Desktop)"); return 3
    env=dict(os.environ,PYTHONPATH=str(CU/".venv"/"Lib"/"site-packages"))
    proc=subprocess.Popen([str(PY),"main.py","--listen","127.0.0.1","--port",str(PORT),"--disable-auto-launch","--disable-api-nodes"],cwd=str(CU),env=env,
                          stdout=open(HERE/"comfyui_server.log","w",encoding="utf-8"),stderr=subprocess.STDOUT)
    try:
        for _ in range(240):
            try: get("/system_stats",2); break
            except Exception: time.sleep(1)
        else: log("STOP: no start"); return 4
        log("ComfyUI up")
        inp=CU/"input"
        for job in spec["jobs"]:
            f=(HERE/job["first"]).resolve(); fn="LT_"+f.name; shutil.copyfile(f,inp/fn); ln=None
            if job.get("last"):
                l=(HERE/job["last"]).resolve(); ln="LT_"+l.name; shutil.copyfile(l,inp/ln)
            for k,seed in enumerate(job["seeds"]):
                pid=post("/prompt",{"prompt":build(job,seed,fn,ln)})["prompt_id"]; t0=time.time()
                while True:
                    h=get(f"/history/{pid}",30)
                    if pid in h: break
                    if time.time()-t0>2400: log("STOP timeout"); return 5
                    time.sleep(3)
                st=h[pid].get("status",{}); files=[x for o in h[pid].get("outputs",{}).values() for key in ("videos","images","gifs") for x in o.get(key,[])]
                if st.get("status_str")!="success" or not files: log(f"FAIL {job['id']} {json.dumps(st)[:1500]}"); continue
                x=files[0]; src=CU/"output"/x.get("subfolder","")/x["filename"]; dst=out/f"{job['id']}_v{k+1}{src.suffix}"; shutil.copyfile(src,dst)
                log(f"OK {dst.name} seed={seed} {time.time()-t0:.0f}s")
        log("=== done"); return 0
    finally:
        proc.terminate()
        try: proc.wait(30)
        except Exception: proc.kill()
        log("ComfyUI stopped")
if __name__=="__main__": sys.exit(main())
