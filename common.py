"""Shared paths, manifest I/O, filename and retry helpers."""
import json
import random
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.json"
STATE = ROOT / "state.json"
VIDEOS = ROOT / "videos"
AUDIO = ROOT / "audio"
TRANSCRIPTS = ROOT / "transcripts"
LESSON_URL = "https://pddtest.kz/courses/1/{n}"


def load_manifest() -> dict[int, dict]:
    if not MANIFEST.exists():
        return {}
    return {e["lesson"]: e for e in json.loads(MANIFEST.read_text("utf-8"))}


def save_manifest(manifest: dict[int, dict]) -> None:
    """Write via a temp file so a crash never leaves a half-written manifest."""
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps([manifest[n] for n in sorted(manifest)], ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(MANIFEST)


def stem(entry: dict) -> str:
    """File name without extension, like 02_2.1_Общие_обязанности_водителей.

    Build paths as f"{dir / stem}.ext". Path.with_suffix would cut the stem at
    the dot in "2.1".
    """
    title = re.sub(r"\.\s+", " ", entry["title"])
    title = re.sub(r'[\\/:*?"<>|#%]', "", title)
    title = re.sub(r"\s+", "_", title)[:80].strip("._")
    return f"{entry['lesson']:02d}_{title}"


def pause() -> None:
    time.sleep(random.uniform(1, 3))


def retry(fn, what: str, tries: int = 3, base: float = 5, give_up: tuple = ()):
    """Call fn, retrying with exponential backoff. Exceptions in give_up are raised at once."""
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except give_up:
            raise
        except Exception as e:
            if attempt == tries:
                raise
            wait = base * 2 ** (attempt - 1) + random.uniform(0, 1)
            print(f"  {what} failed ({type(e).__name__}: {str(e)[:120]}), retry {attempt}/{tries - 1} in {wait:.0f}s", flush=True)
            time.sleep(wait)


def fmt_duration(seconds) -> str:
    if not seconds:
        return "-"
    m, s = divmod(round(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"
