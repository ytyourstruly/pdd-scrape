"""Extract audio with ffmpeg and transcribe it locally with faster-whisper."""
import ctypes
import glob
import importlib.util
import os
import subprocess
import wave
from pathlib import Path

import numpy as np

from common import AUDIO, ROOT, TRANSCRIPTS, fmt_duration, save_manifest, stem
from download import video_path


def preload_cuda_libs() -> None:
    """Load the pip-installed cuBLAS and cuDNN so ctranslate2 finds them without LD_LIBRARY_PATH."""
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(pkg)
        if not spec or not spec.submodule_search_locations:
            continue
        for lib in sorted(glob.glob(os.path.join(list(spec.submodule_search_locations)[0], "lib", "*.so*"))):
            try:
                ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def load_model(name: str | None = None):
    """large-v3 on a GPU, medium on CPU, unless name overrides the choice."""
    preload_cuda_libs()
    import ctranslate2
    from faster_whisper import WhisperModel

    if ctranslate2.get_cuda_device_count() > 0:
        gpu_name = name or "large-v3"
        try:
            model = WhisperModel(gpu_name, device="cuda", compute_type="float16")
            # Missing CUDA libraries only surface on the first real call, so run one now.
            list(model.transcribe(np.zeros(16000, dtype=np.float32), vad_filter=False)[0])
            return model, f"{gpu_name} on GPU (float16)"
        except Exception as e:
            print(f"transcribe: GPU unusable ({type(e).__name__}: {str(e)[:150]}), using CPU", flush=True)
    cpu_name = name or "medium"
    return WhisperModel(cpu_name, device="cpu", compute_type="int8"), f"{cpu_name} on CPU (int8)"


def extract_audio(video: Path, wav: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )


def load_audio(wav: Path) -> np.ndarray:
    """Read the 16 kHz mono wav ffmpeg wrote. faster-whisper's own decoder fails on PyAV 19."""
    with wave.open(str(wav), "rb") as f:
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, "utf-8")
    tmp.replace(path)


def transcribe_file(model, wav: Path):
    segments, info = model.transcribe(
        load_audio(wav), language=None, beam_size=5, vad_filter=True, condition_on_previous_text=False
    )
    out, last_pct = [], -1
    for seg in segments:
        out.append((seg.start, seg.end, seg.text.strip()))
        pct = int(seg.end / info.duration * 100) // 10 * 10
        if pct != last_pct:
            print(f"  {pct}%", end="", flush=True)
            last_pct = pct
    print()
    return out, info


def build_combined(manifest: dict) -> None:
    parts = ["# PDD course transcripts\n"]
    for n in sorted(manifest):
        entry = manifest[n]
        txt = Path(f"{TRANSCRIPTS / stem(entry)}.txt") if entry.get("title") else None
        if entry.get("transcript_status") != "ok" or not txt or not txt.exists():
            continue
        parts.append(
            f"## Lesson {n}: {entry['title']}\n\n"
            f"Language: {entry['language']}. Duration: {fmt_duration(entry.get('duration'))}.\n\n"
            f"{txt.read_text('utf-8').strip()}\n"
        )
    write_atomic(ROOT / "all_transcripts.md", "\n".join(parts))


def run(numbers, manifest: dict, skip_existing: bool = True, model_name: str | None = None) -> None:
    TRANSCRIPTS.mkdir(exist_ok=True)
    AUDIO.mkdir(exist_ok=True)
    model = None
    for n in numbers:
        entry = manifest.get(n)
        if not entry or entry.get("download_status") != "ok":
            print(f"transcribe: [{n}] skipped, video not downloaded", flush=True)
            continue
        entry.setdefault("errors", {})
        base = f"{TRANSCRIPTS / stem(entry)}"
        txt, srt = Path(f"{base}.txt"), Path(f"{base}.srt")

        if skip_existing and txt.exists() and srt.exists() and entry.get("transcript_status") == "ok" and entry.get("language"):
            print(f"transcribe: [{n}] exists, skipping", flush=True)
            continue

        wav = Path(f"{AUDIO / stem(entry)}.wav")
        try:
            if model is None:
                model, label = load_model(model_name)
                print(f"transcribe: model {label}", flush=True)
            print(f"transcribe: [{n}] {entry['title']}", flush=True)
            extract_audio(video_path(entry), wav)
            segments, info = transcribe_file(model, wav)
            write_atomic(srt, "\n".join(
                f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n" for i, (a, b, t) in enumerate(segments, 1)
            ))
            write_atomic(txt, "\n".join(t for _, _, t in segments) + "\n")  # written last, marks the lesson done
            entry.update(
                transcript_status="ok",
                language=info.language,
                language_probability=round(info.language_probability, 3),
            )
            entry["errors"].pop("transcribe", None)
            print(f"transcribe: [{n}] ok, language {info.language} ({info.language_probability:.2f}), {len(segments)} segments", flush=True)
        except Exception as e:
            entry.update(transcript_status="failed")
            entry["errors"]["transcribe"] = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"transcribe: [{n}] FAILED, {entry['errors']['transcribe']}", flush=True)
        finally:
            wav.unlink(missing_ok=True)
        save_manifest(manifest)
