"""Log in with Playwright, reuse the saved session, and read each lesson's title and video URL."""
import os

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from common import LESSON_URL, ROOT, STATE, pause, retry, save_manifest

AUTH_URL = "https://pddtest.kz/auth"
VIDEO_KEY = "videos_ru_v1"  # Russian version. The site also has videos_kz_v1.


class NotLoggedIn(Exception):
    pass


class LoginFailed(Exception):
    pass


def login(ctx) -> None:
    """Two-step login form. Reads PDD_USER and PDD_PASS from .env and never prints them."""
    load_dotenv(ROOT / ".env")
    user, password = os.environ["PDD_USER"], os.environ["PDD_PASS"]
    page = ctx.new_page()
    try:
        page.goto(AUTH_URL, wait_until="networkidle")
        page.fill("input[name=username]", user)
        page.click("text=Продолжить")
        page.wait_for_selector("input[name=password]", state="visible", timeout=15000)
        page.fill("input[name=password]", password)
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/auth/authorize/password")
        ) as response:
            page.click("button:has-text('Войти')")
        if not response.value.ok:
            try:
                reason = response.value.json().get("error")
            except Exception:
                reason = None
            raise LoginFailed(f"HTTP {response.value.status} {reason or ''}".strip())
        page.wait_for_url(lambda url: "/auth" not in url, timeout=15000)
    finally:
        page.close()
    save_state(ctx)


def save_state(ctx) -> None:
    ctx.storage_state(path=str(STATE))
    os.chmod(STATE, 0o600)


def read_lesson(page, n: int) -> dict:
    """Open the lesson page and read the lesson API response the page itself requests."""
    try:
        with page.expect_response(
            lambda r: r.url.split("?")[0].endswith(f"/courses/lessons/{n}"), timeout=20000
        ) as response:
            page.goto(LESSON_URL.format(n=n), wait_until="domcontentloaded")
    except PlaywrightTimeout:
        if "/auth" in page.url or "/sso" in page.url:
            raise NotLoggedIn()
        raise
    resp = response.value
    if resp.status in (401, 403):
        raise NotLoggedIn()
    if not resp.ok:
        raise RuntimeError(f"lesson API returned HTTP {resp.status}")

    data = resp.json()
    sources = data.get("attachments", {}).get(VIDEO_KEY) or []
    if not sources:
        raise RuntimeError(f"no {VIDEO_KEY} attachment in lesson API response")
    base = sources[0]
    return {
        "title": data.get("title_ru") or page.locator("h1").first.inner_text(timeout=5000),
        "video_source": base if base.endswith(".m3u8") else base.rstrip("/") + "/master.m3u8",
    }


def run(numbers, manifest: dict, skip_existing: bool = True) -> None:
    todo = [
        n for n in numbers
        if not (skip_existing and manifest.get(n, {}).get("status") == "ok" and manifest[n].get("video_source"))
    ]
    if not todo:
        print("scrape: every lesson in range is already in the manifest")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(STATE) if STATE.exists() else None)
        page = ctx.new_page()
        logged_in_this_run = False
        try:
            for i, n in enumerate(todo):
                if i:
                    pause()
                entry = manifest.setdefault(n, {"lesson": n, "url": LESSON_URL.format(n=n)})
                entry.setdefault("errors", {})
                try:
                    try:
                        info = retry(lambda: read_lesson(page, n), f"lesson {n}", give_up=(NotLoggedIn,))
                    except NotLoggedIn:
                        if logged_in_this_run:
                            raise LoginFailed("session rejected right after logging in")
                        print("scrape: no valid session, logging in", flush=True)
                        login(ctx)
                        logged_in_this_run = True
                        info = retry(lambda: read_lesson(page, n), f"lesson {n}", give_up=(NotLoggedIn,))
                    entry.update(info, status="ok")
                    entry["errors"].pop("scrape", None)
                    print(f"scrape: [{n}] {info['title']}", flush=True)
                except LoginFailed:
                    raise
                except Exception as e:
                    entry.update(status="failed")
                    entry["errors"]["scrape"] = f"{type(e).__name__}: {str(e)[:200]}"
                    print(f"scrape: [{n}] FAILED, {entry['errors']['scrape']}", flush=True)
                save_manifest(manifest)
        finally:
            save_state(ctx)  # keep refreshed tokens for the next run
            browser.close()
