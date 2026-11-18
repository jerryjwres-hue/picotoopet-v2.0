# PicotooPet Studio Worker v2 (Windows GPU). Thin loop; task logic lives in worker_tasks.py and is re-loaded for every task,
# so planners can update behaviour without restarting this process.
# Task file (JSON) in _queue/inbox:  {"runner": "<script>.py in this folder" | "selftest", "args": ["..."], "jobs": "jobs_x.json", "note": "..."}
import importlib, json, shutil, time, traceback, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; Q = HERE.parent / "_queue"; sys.path.insert(0, str(HERE))
for d in ("inbox", "running", "done", "failed"): (Q / d).mkdir(parents=True, exist_ok=True)
def log(m):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + m; print(line, flush=True)
    with open(Q / "worker.log", "a", encoding="utf-8") as f: f.write(line + "\n")
log("=== worker v2 start")
while True:
    (Q / "worker_heartbeat.txt").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + " v2", encoding="utf-8")
    if (Q / "STOP").exists(): log("STOP file found, exiting"); (Q / "STOP").unlink(); break
    tasks = sorted((Q / "inbox").glob("*.json"))
    if not tasks: time.sleep(5); continue
    tf = tasks[0]; run = Q / "running" / tf.name; shutil.move(str(tf), str(run)); log(f"run {tf.name}")
    try:
        import worker_tasks; importlib.reload(worker_tasks)
        res = worker_tasks.run_task(run, log); dest = "done" if res.get("ok") else "failed"
    except Exception as e:
        res = {"task": run.stem, "ok": False, "error": repr(e), "trace": traceback.format_exc()[-2000:]}; dest = "failed"
    (Q / dest / f"{run.stem}.result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.move(str(run), str(Q / dest / run.name)); log(f"{dest} {run.name} {res.get('seconds','')}s")
