"""Download each lesson's HLS stream with yt-dlp."""
import subprocess
from pathlib import Path

from yt_dlp import YoutubeDL

from common import VIDEOS, pause, retry, save_manifest, stem


# The playlist also offers 1080p (about twice the size). The site's own player uses 720p.
FORMAT = "bv*[height<=720]+ba/b[height<=720]"


def probe_duration(path: Path) -> float | None:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def video_path(entry: dict) -> Path:
    return Path(f"{VIDEOS / stem(entry)}.mp4")


def fetch(entry: dict, overwrite: bool) -> None:
    opts = {
        "outtmpl": f"{VIDEOS / stem(entry)}.%(ext)s",
        "format": FORMAT,
        "merge_output_format": "mp4",
        "http_headers": {"Referer": "https://pddtest.kz/"},
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "fragment_retries": 10,
        "overwrites": overwrite,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with YoutubeDL(opts) as ydl:
        ydl.download([entry["video_source"]])


def run(numbers, manifest: dict, skip_existing: bool = True) -> None:
    VIDEOS.mkdir(exist_ok=True)
    for n in numbers:
        entry = manifest.get(n)
        if not entry or not entry.get("video_source"):
            print(f"download: [{n}] skipped, no video source in manifest", flush=True)
            continue
        entry.setdefault("errors", {})
        path = video_path(entry)

        # yt-dlp renames to the final name only when the merge finishes, so an existing file is complete.
        if skip_existing and path.exists() and (duration := probe_duration(path)):
            entry.update(download_status="ok", video_file=path.name, duration=round(duration, 1))
            entry["errors"].pop("download", None)
            print(f"download: [{n}] exists, skipping ({path.name})", flush=True)
            save_manifest(manifest)
            continue

        pause()
        print(f"download: [{n}] {entry['title']}", flush=True)
        try:
            retry(lambda: fetch(entry, overwrite=not skip_existing), f"download {n}")
            duration = probe_duration(path)
            if not duration:
                raise RuntimeError(f"{path.name} is missing or unreadable after download")
            entry.update(download_status="ok", video_file=path.name, duration=round(duration, 1))
            entry["errors"].pop("download", None)
            print(f"download: [{n}] ok, {path.stat().st_size / 1e6:.0f} MB", flush=True)
        except Exception as e:
            entry.update(download_status="failed")
            entry["errors"]["download"] = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"download: [{n}] FAILED, {entry['errors']['download']}", flush=True)
        save_manifest(manifest)
