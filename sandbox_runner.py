import json, os, sys, subprocess, urllib.request
from pathlib import Path

HF = os.environ["HF_WORKFLOWS"]
payload = json.loads(Path("payload.json").read_text())
Path("voice.lock").write_text("d8ba9f14-8a24-44db-932b-99e16c45bd32 preset\n")
script = {
  "NARRATION_LANGUAGE": "en",
  "blocks": [{"n": int(k), "vo_line": payload["lines"][k]} for k in "123456"],
}
Path("script_manifest.json").write_text(json.dumps(script, ensure_ascii=False, indent=2))
Path("work/blocks").mkdir(parents=True, exist_ok=True)
Path("work/voices").mkdir(parents=True, exist_ok=True)
Path("work/output").mkdir(parents=True, exist_ok=True)

for i in range(1, 7):
    k = str(i)
    urllib.request.urlretrieve(payload["videos"][k], f"work/blocks/block{i:02d}.mp4")
    urllib.request.urlretrieve(payload["voices"][k], f"work/voices/take{i:02d}.mp3")
    print("downloaded", i, flush=True)

for i in range(1, 7):
    subprocess.check_call([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", f"work/voices/take{i:02d}.mp3",
        "-ac", "1", "-ar", "24000",
        "-af", "areverse,atrim=start=0.030,asetpts=N/SR/TB,afade=t=in:st=0:d=0.060,areverse",
        "-y", f"work/voices/voice{i:02d}.wav",
    ])

measure = f"{HF}/faceless-video/scripts/measure_narration_takes.py"
p = subprocess.run([
    sys.executable, measure,
    "--script", "script_manifest.json",
    "--voice-dir", "work/voices",
    "--duration-seconds", "60",
], capture_output=True, text=True)
Path("work/output/gate5.json").write_text(p.stdout)
print(p.stdout[:2000], flush=True)
gate = json.loads(p.stdout)
if p.returncode != 0 or not gate.get("valid"):
    print("GATE5_FAIL", flush=True)
    sys.exit(42)

pairs = Path("pairs.txt")
pairs.write_text("".join(
    f"work/blocks/block{i:02d}.mp4 work/voices/voice{i:02d}.wav\n" for i in range(1, 7)
))
subprocess.check_call([
    "bash", f"{HF}/faceless-video/scripts/assemble_final.sh",
    "--out", "work/output/final_clean.mp4",
    "--blocks", "6",
    "--manifest", "pairs.txt",
    "--script", "script_manifest.json",
])

# Phase 7 — EN clean motion captions
subprocess.check_call(["bash", f"{HF}/subtitles/scripts/fetch_fonts.sh"])
final = Path("work/output/final.mp4")
has_fw = subprocess.call([sys.executable, "-c", "import faster_whisper"]) == 0
if has_fw:
    subprocess.check_call([
        sys.executable, f"{HF}/subtitles/scripts/audio_to_captions.py",
        "work/output/final_clean.mp4",
        "--srt", "work/output/final.srt",
        "--per-block", "work/output/final_clean.mp4.assembly.json",
        "--voice-dir", "work/voices",
        "--script", "script_manifest.json",
        "--language", "en",
    ])
    subprocess.check_call([
        "bash", f"{HF}/subtitles/scripts/burn_caps_clean.sh",
        "--in", "work/output/final_clean.mp4",
        "--srt", "work/output/final.srt",
        "--out", str(final),
    ])
else:
    print("CAPTIONS_UNAVAILABLE=faster_whisper", flush=True)
    final.write_bytes(Path("work/output/final_clean.mp4").read_bytes())

subprocess.check_call([
    "ffprobe", "-v", "error",
    "-show_entries", "format=duration",
    "-of", "csv=p=0", str(final),
])
print("FINAL_BYTES", final.stat().st_size, flush=True)

# PUT with curl --upload-file (required)
p = subprocess.run([
    "curl", "-sS", "-o", "/tmp/put_out.txt", "-w", "%{http_code}",
    "-f", "-X", "PUT", "-H", "Content-Type: video/mp4",
    "--upload-file", str(final), payload["upload_url"],
], capture_output=True, text=True)
print("PUT_HTTP", p.stdout, p.stderr, flush=True)
assert p.stdout.strip() == "200", p
print("ASSEMBLE_UPLOAD_OK", payload["media_id"], flush=True)
