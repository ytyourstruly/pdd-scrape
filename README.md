# PDD course downloader and transcriber

Downloads the Russian-language lesson videos from https://pddtest.kz/courses/1/N with your own
logged-in account, then transcribes them locally with faster-whisper. The videos are plain
unencrypted HLS, so nothing here touches DRM.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
sudo apt install ffmpeg        # or your platform's equivalent, ffprobe must be on PATH too
```

Create `.env` in this folder (it is listed in `.gitignore`):

```
PDD_USER=your login, IIN, phone or email
PDD_PASS=your password
```

If the password contains a double quote, wrap the value in single quotes.

## Usage

```bash
python run.py --start 1 --end 42 --skip-existing
python run.py --start 1 --end 1                  # test on one lesson
python run.py --stages download,transcribe       # skip the scrape stage
python run.py --model medium                     # override the model
```

`--skip-existing` is on by default. `--no-skip-existing` redoes everything in the range.

The run has three stages, and each one skips lessons it already finished, so you can stop with
Ctrl-C and rerun the same command to resume.

1. **scrape** logs in once, saves the session to `state.json`, and records each lesson's title and
   video URL in `manifest.json`.
2. **download** fetches the video with yt-dlp into `videos/NN_title.mp4`.
3. **transcribe** extracts 16 kHz mono audio with ffmpeg, runs faster-whisper with language
   auto-detection, and writes `transcripts/NN_title.txt` and `.srt`. It then rebuilds
   `all_transcripts.md` from every finished lesson.

A failed lesson is logged in `manifest.json` under `errors` and does not stop the run. The table
printed at the end shows the status, duration and detected language for each lesson.

## GPU

On an NVIDIA GPU the model is `large-v3` in float16 (about 4 GB of VRAM). The CUDA 12 libraries
come from the `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` pip packages, and `transcribe.py`
loads them itself. Without a usable GPU it falls back to `medium` on the CPU, which is much
slower.
## Files

| Path | Contents |
| --- | --- |
| `manifest.json` | lesson number, URL, title, video source, and per-stage status and errors |
| `state.json` | saved browser session, treat it like a password |
| `videos/` | downloaded videos |
| `transcripts/` | `.txt` and `.srt` per lesson |
| `all_transcripts.md` | every transcript with a heading per lesson |
