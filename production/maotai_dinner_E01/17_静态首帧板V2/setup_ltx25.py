# Upgrade local ComfyUI v0.29.0 -> v0.45.6 (LTX-2.5 needs >=0.32), keep torch pinned, reuse LTX Desktop's LTX-2.5 weights via extra_model_paths.yaml.
# Rollback: git -C ComfyUI checkout v0.29.0 ; reinstall requirements.
import os, sys, time, subprocess, shutil, json
from pathlib import Path
HERE=Path(__file__).resolve().parent; LOG=HERE/"setup_ltx25_log.txt"
C=Path(r"D:\opc in D\AI\ComfyUI"); CU=C/"ComfyUI"; VPY=CU/".venv"/"Scripts"/"python.exe"; SPY=C/"standalone-env"/"python.exe"
LTXM=Path(r"D:\opc in D\AI\LTX25\models")
TAG="v0.45.6"
def log(m):
    line=time.strftime("%H:%M:%S ")+m; print(line,flush=True)
    with open(LOG,"a",encoding="utf-8") as f: f.write(line+"\n")
def run(cmd,**kw):
    log("$ "+" ".join(map(str,cmd))[:300]); r=subprocess.run(cmd,capture_output=True,text=True,**kw)
    log((r.stdout[-2500:]+"\n"+r.stderr[-2500:]).strip()); return r.returncode
def main():
    log("=== setup LTX-2.5 start")
    if run(["git","-C",str(CU),"checkout",TAG]): log("STOP: git checkout failed"); return 2
    cons=CU/"_pin_torch.txt"; cons.write_text("torch==2.10.0+cu130\ntorchvision==0.25.0+cu130\ntorchaudio==2.10.0+cu130\n")
    uv=shutil.which("uv") or next((str(p) for p in C.rglob("uv.exe")), None)
    req=str(CU/"requirements.txt")
    if uv:
        rc=run([uv,"pip","install","--python",r"..\standalone-env\python.exe","--target",r".venv\Lib\site-packages","-r","requirements.txt","-c","_pin_torch.txt","--extra-index-url","https://download.pytorch.org/whl/cu130","--index-strategy","unsafe-best-match"],cwd=str(CU))
    else:
        rc=run([str(SPY),"-m","pip","--python",str(VPY),"install","-r",req,"-c",str(cons),"--extra-index-url","https://download.pytorch.org/whl/cu130"])
    if rc: log("STOP: requirements install failed (ComfyUI code is at %s; rollback with git checkout v0.29.0)"%TAG); return 3
    y=CU/"extra_model_paths.yaml"
    y.write_text(f"""ltx_desktop:
    base_path: {LTXM.as_posix()}
    diffusion_models: ltx-2.5
    text_encoders: |
        ltx-2.5
        gemma-4-E2B-it
    vae: ltx-2.5
    latent_upscale_models: ltx-2.5
    loras: |
        loras
        ic-loras
""",encoding="utf-8"); log("wrote extra_model_paths.yaml")
    r=subprocess.run([str(SPY),"-c","import importlib.metadata as m\nfor p in ('comfyui-frontend-package','comfyui-workflow-templates','comfy-kitchen','torch'):\n  try: print(p,m.version(p))\n  except Exception as e: print(p,'?')\nimport comfyui_workflow_templates as t, os\nprint(os.path.dirname(t.__file__))"],capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(CU/'.venv'/'Lib'/'site-packages')))
    log(r.stdout+r.stderr[-500:])
    log("=== setup done"); return 0
if __name__=="__main__": sys.exit(main())
