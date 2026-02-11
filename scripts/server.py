"""
DrissionPage browser automation server for OpenClaw.
Exposes a FastAPI HTTP API wrapping DrissionPage's ChromiumPage.
"""

import base64
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from DrissionPage import ChromiumPage, ChromiumOptions
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = Path.home() / ".openclaw" / "browser" / "drissionpage"
USER_DATA_DIR = DATA_DIR / "user-data"
CDP_PORT = 18860
PROXY = os.environ.get("BROWSER_PROXY", "")  # e.g. socks5://127.0.0.1:18870

USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("drissionpage-server")

# ---------------------------------------------------------------------------
# Browser singleton
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_page: Optional[ChromiumPage] = None


def _make_options() -> ChromiumOptions:
    co = ChromiumOptions()
    co.set_browser_path("/usr/bin/chromium")
    co.set_local_port(CDP_PORT)
    co.set_user_data_path(str(USER_DATA_DIR))
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--start-maximized")
    if PROXY:
        co.set_argument("--proxy-server", PROXY)
        log.info("Using proxy: %s", PROXY)
    return co


def _get_page() -> ChromiumPage:
    global _page
    if _page is None:
        log.info("Launching browser...")
        _page = ChromiumPage(addr_or_opts=_make_options())
        log.info("Browser ready")
    return _page


def _restart_browser() -> ChromiumPage:
    global _page
    if _page is not None:
        try:
            _page.quit()
        except Exception:
            pass
    _page = None
    return _get_page()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class NavigateRequest(BaseModel):
    url: str

class SelectorRequest(BaseModel):
    selector: str
    timeout: float = 10

class MultiSelectorRequest(BaseModel):
    selector: str
    limit: int = 50

class ClickRequest(BaseModel):
    selector: str
    by_js: bool = False
    timeout: float = 10

class TypeRequest(BaseModel):
    selector: str
    text: str
    clear: bool = True
    by_js: bool = False
    timeout: float = 10

class PressRequest(BaseModel):
    key: str

class ScrollRequest(BaseModel):
    delta_x: int = 0
    delta_y: int = 500

class HoverRequest(BaseModel):
    selector: str
    timeout: float = 10

class WaitElementRequest(BaseModel):
    selector: str
    timeout: float = 30
    state: str = Field(default="displayed", description="displayed | hidden")

class WaitTextRequest(BaseModel):
    text: str
    timeout: float = 30

class WaitUrlRequest(BaseModel):
    url: str
    timeout: float = 30
    contains: bool = True

class WaitTimeRequest(BaseModel):
    seconds: float

class EvaluateRequest(BaseModel):
    script: str

class CookieSetRequest(BaseModel):
    cookies: list[dict[str, Any]]

class TabSwitchRequest(BaseModel):
    index: int = 0

class SnapshotRequest(BaseModel):
    max_length: int = 80000


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="DrissionPage Browser Server", version="0.1.0")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": str(exc)})


def ok(data: Any = None, **kwargs) -> dict:
    result = {"ok": True}
    if data is not None:
        result["data"] = data
    result.update(kwargs)
    return result


def err(msg: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"ok": False, "error": msg})


# ---------------------------------------------------------------------------
# Session / Status
# ---------------------------------------------------------------------------

@app.get("/status")
def status():
    with _lock:
        info = {"proxy": PROXY or "direct"}
        if _page is None:
            return ok(browser="not_started", **info)
        try:
            url = _page.url
            title = _page.title
            return ok(browser="running", url=url, title=title, **info)
        except Exception as e:
            return ok(browser="error", detail=str(e), **info)


@app.post("/browser/restart")
def browser_restart():
    with _lock:
        _restart_browser()
    return ok(message="Browser restarted")


@app.post("/browser/new-tab")
def browser_new_tab():
    with _lock:
        page = _get_page()
        page.new_tab()
    return ok()


@app.get("/browser/tabs")
def browser_tabs():
    with _lock:
        page = _get_page()
        tabs = page.tab_ids
        return ok(tabs=tabs, count=len(tabs))


@app.post("/browser/switch-tab")
def browser_switch_tab(req: TabSwitchRequest):
    with _lock:
        page = _get_page()
        tabs = page.tab_ids
        if req.index >= len(tabs):
            return err(f"Tab index {req.index} out of range (have {len(tabs)} tabs)")
        page.to_tab(tabs[req.index])
    return ok()


@app.post("/browser/close-tab")
def browser_close_tab():
    with _lock:
        page = _get_page()
        tabs = page.tab_ids
        if len(tabs) <= 1:
            return err("Cannot close the last tab")
        page.close()
    return ok()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

@app.post("/navigate")
def navigate(req: NavigateRequest):
    with _lock:
        page = _get_page()
        page.get(req.url)
        return ok(url=page.url, title=page.title)


@app.get("/url")
def get_url():
    with _lock:
        page = _get_page()
        return ok(url=page.url)


@app.post("/back")
def go_back():
    with _lock:
        page = _get_page()
        page.back()
        return ok(url=page.url)


@app.post("/forward")
def go_forward():
    with _lock:
        page = _get_page()
        page.forward()
        return ok(url=page.url)


@app.post("/refresh")
def refresh():
    with _lock:
        page = _get_page()
        page.refresh()
        return ok(url=page.url)


# ---------------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------------

@app.get("/title")
def get_title():
    with _lock:
        page = _get_page()
        return ok(title=page.title)


@app.get("/text")
def get_text():
    with _lock:
        page = _get_page()
        body = page.ele("tag:body")
        text = body.text if body else ""
        if len(text) > 50000:
            text = text[:50000] + "\n... (truncated)"
        return ok(text=text)


@app.post("/element/text")
def element_text(req: SelectorRequest):
    with _lock:
        page = _get_page()
        el = page.ele(req.selector, timeout=req.timeout)
        if el is None:
            return err(f"Element not found: {req.selector}")
        return ok(text=el.text, tag=el.tag)


@app.post("/elements/text")
def elements_text(req: MultiSelectorRequest):
    with _lock:
        page = _get_page()
        els = page.eles(req.selector)
        results = []
        for el in els[:req.limit]:
            results.append({"text": el.text, "tag": el.tag})
        return ok(elements=results, count=len(results))


@app.post("/element/html")
def element_html(req: SelectorRequest):
    with _lock:
        page = _get_page()
        el = page.ele(req.selector, timeout=req.timeout)
        if el is None:
            return err(f"Element not found: {req.selector}")
        return ok(html=el.html, tag=el.tag)


# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------

@app.post("/click")
def click(req: ClickRequest):
    with _lock:
        page = _get_page()
        el = page.ele(req.selector, timeout=req.timeout)
        if el is None:
            return err(f"Element not found: {req.selector}")
        if req.by_js:
            el.click.by_js()
        else:
            el.click()
        return ok()


@app.post("/type")
def type_text(req: TypeRequest):
    with _lock:
        page = _get_page()
        el = page.ele(req.selector, timeout=req.timeout)
        if el is None:
            return err(f"Element not found: {req.selector}")
        el.input(req.text, clear=req.clear, by_js=req.by_js)
        return ok()


@app.post("/press")
def press_key(req: PressRequest):
    with _lock:
        page = _get_page()
        page.actions.key_down(req.key).key_up(req.key)
        return ok()


@app.post("/scroll")
def scroll(req: ScrollRequest):
    with _lock:
        page = _get_page()
        page.run_js(f"window.scrollBy({{left: {req.delta_x}, top: {req.delta_y}, behavior: 'smooth'}})")
        return ok()


@app.post("/hover")
def hover(req: HoverRequest):
    with _lock:
        page = _get_page()
        el = page.ele(req.selector, timeout=req.timeout)
        if el is None:
            return err(f"Element not found: {req.selector}")
        el.hover()
        return ok()


# ---------------------------------------------------------------------------
# Wait
# ---------------------------------------------------------------------------

@app.post("/wait/element")
def wait_element(req: WaitElementRequest):
    with _lock:
        page = _get_page()
        if req.state == "displayed":
            el = page.ele(req.selector, timeout=req.timeout)
            found = el is not None
        elif req.state == "hidden":
            try:
                page.wait.ele_hidden(req.selector, timeout=req.timeout)
                found = True
            except Exception:
                found = False
        else:
            return err(f"Unknown state: {req.state}")
        return ok(found=found)


@app.post("/wait/text")
def wait_text(req: WaitTextRequest):
    with _lock:
        page = _get_page()
        try:
            el = page.ele(f"text:{req.text}", timeout=req.timeout)
            return ok(found=el is not None)
        except Exception:
            return ok(found=False)


@app.post("/wait/url")
def wait_url(req: WaitUrlRequest):
    with _lock:
        page = _get_page()
        deadline = time.time() + req.timeout
        while time.time() < deadline:
            current = page.url
            if req.contains and req.url in current:
                return ok(matched=True, url=current)
            elif not req.contains and current == req.url:
                return ok(matched=True, url=current)
            time.sleep(0.3)
        return ok(matched=False, url=page.url)


@app.post("/wait/time")
def wait_time(req: WaitTimeRequest):
    time.sleep(req.seconds)
    return ok()


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

@app.post("/screenshot")
def screenshot():
    with _lock:
        page = _get_page()
        path = str(DATA_DIR / "screenshot.png")
        page.get_screenshot(path=path, full_page=True)
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return ok(path=path, base64=b64, format="png")


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
    with _lock:
        page = _get_page()
        result = page.run_js(req.script)
        return ok(result=result)


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------

@app.get("/cookies")
def get_cookies():
    with _lock:
        page = _get_page()
        cookies = page.cookies(as_dict=False, all_info=True)
        return ok(cookies=cookies)


@app.post("/cookies/set")
def set_cookies(req: CookieSetRequest):
    with _lock:
        page = _get_page()
        for cookie in req.cookies:
            page.set.cookies(cookie)
        return ok()


@app.post("/cookies/clear")
def clear_cookies():
    with _lock:
        page = _get_page()
        page.set.cookies.clear()
        return ok()


# ---------------------------------------------------------------------------
# Snapshot — structured text representation of the page
# ---------------------------------------------------------------------------

@app.get("/snapshot")
def snapshot(max_length: int = 80000):
    with _lock:
        page = _get_page()
        return ok(snapshot=_build_snapshot(page, max_length), url=page.url, title=page.title)


def _build_snapshot(page: ChromiumPage, max_length: int) -> str:
    """Build an agent-friendly text snapshot of the visible page."""
    parts: list[str] = []
    parts.append(f"Page: {page.title}")
    parts.append(f"URL: {page.url}")
    parts.append("")

    # Headings
    headings = page.eles("css:h1,h2,h3,h4,h5,h6")
    if headings:
        parts.append("## Headings")
        for h in headings[:30]:
            text = h.text.strip()
            if text:
                parts.append(f"  [{h.tag}] {text}")
        parts.append("")

    # Navigation / links
    nav_links = page.eles("css:nav a")
    if nav_links:
        parts.append("## Navigation")
        for a in nav_links[:30]:
            text = a.text.strip()
            href = a.attr("href") or ""
            if text:
                parts.append(f"  [{text}]({href})")
        parts.append("")

    # Forms and inputs
    inputs = page.eles("css:input,textarea,select")
    if inputs:
        parts.append("## Inputs")
        for inp in inputs[:30]:
            itype = inp.attr("type") or inp.tag
            name = inp.attr("name") or inp.attr("id") or ""
            placeholder = inp.attr("placeholder") or ""
            value = inp.attr("value") or ""
            label = _find_label(page, inp)
            desc = label or placeholder or name or itype
            parts.append(f"  [{itype}] {desc}" + (f" = \"{value}\"" if value else ""))
        parts.append("")

    # Buttons
    buttons = page.eles("css:button,[role=button],input[type=submit],input[type=button]")
    if buttons:
        parts.append("## Buttons")
        seen = set()
        for btn in buttons[:30]:
            text = btn.text.strip() or btn.attr("aria-label") or btn.attr("value") or ""
            if text and text not in seen:
                seen.add(text)
                parts.append(f"  [{text}]")
        parts.append("")

    # Links (non-nav)
    links = page.eles("css:main a, article a, [role=main] a")
    if links:
        parts.append("## Links")
        seen = set()
        for a in links[:40]:
            text = a.text.strip()
            href = a.attr("href") or ""
            if text and text not in seen:
                seen.add(text)
                parts.append(f"  [{text}]({href})")
        parts.append("")

    # Main text content
    main = page.ele("css:main, article, [role=main]", timeout=1)
    if main is None:
        main = page.ele("tag:body")
    if main:
        text = main.text.strip()
        if text:
            parts.append("## Content")
            if len(text) > max_length // 2:
                text = text[:max_length // 2] + "\n... (truncated)"
            parts.append(text)
            parts.append("")

    result = "\n".join(parts)
    if len(result) > max_length:
        result = result[:max_length] + "\n... (truncated)"
    return result


def _find_label(page, element) -> str:
    """Try to find a label for an input element."""
    el_id = element.attr("id")
    if el_id:
        try:
            label = page.ele(f"css:label[for='{el_id}']", timeout=0.5)
            if label:
                return label.text.strip()
        except Exception:
            pass
    aria = element.attr("aria-label")
    if aria:
        return aria
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=18850)
