import subprocess, os, sys, json
V="/mnt/user-data/uploads/茅台晚餐_连续性V2/24_场景包/video_v1/"
FONT="/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"
SHOTS=json.loads(sys.argv[1]) if len(sys.argv)>1 else None
os.makedirs("seg",exist_ok=True)
segs=[]
for i,(clip,cap) in enumerate(SHOTS):
    src=V+clip+".mp4"; out=f"seg/{i:02d}.mp4"
    dur=float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",src]).decode())
    vf="scale=1080:1920:flags=lanczos,fps=24,format=yuv420p"
    if cap:
        tf=f"seg/{i:02d}.txt"; open(tf,"w").write(cap)
        vf+=(f",drawtext=fontfile={FONT}:textfile={tf}:fontsize=68:fontcolor=white:borderw=7:bordercolor=black@0.85"
             f":x=(w-text_w)/2:y=h*0.20:alpha='min(1,t/0.25)'")
    af=f"aresample=48000,aformat=channel_layouts=stereo,afade=t=in:d=0.06,afade=t=out:st={max(0,dur-0.08):.3f}:d=0.08,volume=0.7"
    subprocess.run(["ffmpeg","-v","error","-y","-i",src,"-vf",vf,"-af",af,"-c:v","libx264","-preset","veryfast","-crf","18","-c:a","aac","-b:a","192k","-shortest",out],check=True)
    segs.append(out)
open("seg/list.txt","w").write("".join(f"file '{os.path.basename(s)}'\n" for s in segs))
subprocess.run(["ffmpeg","-v","error","-y","-f","concat","-safe","0","-i","seg/list.txt","-c:v","copy","-af","loudnorm=I=-14:TP=-1.5:LRA=11","-c:a","aac","-b:a","192k","E01_cut.mp4"],check=True)
print(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0","E01_cut.mp4"]).decode())
