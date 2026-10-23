"""Scrape, download and transcribe the PDD course videos. Rerun at any time to resume."""
import argparse
import sys

import download
import scraper
import transcribe
from common import fmt_duration, load_manifest

STAGES = ("scrape", "download", "transcribe")


def summary(manifest: dict, numbers) -> None:
    mark = {"ok": "OK", "failed": "FAILED"}
    print(f"\n{'lesson':>6}  {'download':<9} {'transcript':<10} {'duration':>8}  {'lang':<5} title")
    for n in numbers:
        e = manifest.get(n, {})
        print(
            f"{n:>6}  {mark.get(e.get('download_status'), '-'):<9} {mark.get(e.get('transcript_status'), '-'):<10} "
            f"{fmt_duration(e.get('duration')):>8}  {e.get('language', '-'):<5} {e.get('title', '-')}"
        )
        for stage, msg in e.get("errors", {}).items():
            print(f"{'':>6}  {stage} error: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=1, help="first lesson (default 1)")
    ap.add_argument("--end", type=int, default=42, help="last lesson (default 42)")
    ap.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True,
                    help="skip lessons that are already done (default on, --no-skip-existing redoes them)")
    ap.add_argument("--stages", default=",".join(STAGES), help="comma-separated subset of scrape,download,transcribe")
    ap.add_argument("--model", help="faster-whisper model (default large-v3 on GPU, medium on CPU)")
    args = ap.parse_args()

    stages = args.stages.split(",")
    if args.start > args.end or any(s not in STAGES for s in stages):
        ap.error("need --start <= --end and --stages from scrape,download,transcribe")
    numbers = range(args.start, args.end + 1)
    manifest = load_manifest()

    try:
        if "scrape" in stages:
            try:
                scraper.run(numbers, manifest, args.skip_existing)
            except scraper.LoginFailed as e:
                print(f"scrape: login failed ({e}). Check PDD_USER and PDD_PASS in .env.", file=sys.stderr)
        if "download" in stages:
            download.run(numbers, manifest, args.skip_existing)
        if "transcribe" in stages:
            transcribe.run(numbers, manifest, args.skip_existing, args.model)
            transcribe.build_combined(manifest)
    except KeyboardInterrupt:
        print("\ninterrupted, rerun the same command to resume", file=sys.stderr)
        return 130
    finally:
        summary(manifest, numbers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
