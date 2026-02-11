---
name: drissionpage-browser
description: Stealth web browser via DrissionPage — bypasses bot detection on sites like X.com that block standard automation.
metadata:
  {
    "openclaw":
      {
        "emoji": "🕸️",
        "requires": { "bins": ["python3", "curl"] },
        "os": ["linux"],
      },
  }
---

# 🕸️ DrissionPage Browser

_Stealth browsing that doesn't get blocked_

A local browser automation server using DrissionPage (not WebDriver), invisible to bot detection. Use this when the built-in browser gets blocked.

## Lifecycle

```bash
# Start (auto-provisions venv + deps on first run)
bash {baseDir}/scripts/manage.sh start

# Start with SOCKS proxy (for residential IP routing)
BROWSER_PROXY=socks5://127.0.0.1:18870 bash {baseDir}/scripts/manage.sh start

# Check status
bash {baseDir}/scripts/manage.sh status

# Stop
bash {baseDir}/scripts/manage.sh stop

# View logs
bash {baseDir}/scripts/manage.sh logs
```

Server runs on `http://127.0.0.1:18850`. All examples below use that base URL.

## Quick Start

```bash
# 1. Check server
curl -s http://127.0.0.1:18850/status

# 2. Navigate
curl -s -X POST http://127.0.0.1:18850/navigate \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://x.com"}'

# 3. Get page snapshot (best for understanding page structure)
curl -s http://127.0.0.1:18850/snapshot

# 4. Click an element
curl -s -X POST http://127.0.0.1:18850/click \
  -H 'Content-Type: application/json' \
  -d '{"selector": "text:Log in"}'

# 5. Type into a field
curl -s -X POST http://127.0.0.1:18850/type \
  -H 'Content-Type: application/json' \
  -d '{"selector": "css:input[name=text]", "text": "hello"}'
```

## Selectors

DrissionPage selectors use prefix syntax:

| Prefix | Example | Matches |
|--------|---------|---------|
| `text:` | `text:Log in` | Element containing text (fuzzy) |
| `text=` | `text=Log in` | Element with exact text |
| `css:` | `css:input[type=email]` | CSS selector |
| `xpath:` | `xpath://div[@id='main']` | XPath |
| `tag:` | `tag:button` | HTML tag name |
| `@attr=` | `@name=username` | Attribute exact match |
| `@attr:` | `@placeholder:email` | Attribute fuzzy match |
| `#id` | `#login-form` | Element by ID |
| `.class` | `.btn-primary` | Element by class |

Default (no prefix) searches by text content.

## Endpoints

### Navigation

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/navigate` | `{"url": "..."}` | Go to URL |
| GET | `/url` | — | Get current URL |
| POST | `/back` | — | Go back |
| POST | `/forward` | — | Go forward |
| POST | `/refresh` | — | Reload page |

### Page Content

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/title` | — | Page title |
| GET | `/text` | — | Body text (truncated 50k) |
| GET | `/snapshot` | `?max_length=80000` | Structured page overview |
| POST | `/element/text` | `{"selector": "..."}` | Element text |
| POST | `/elements/text` | `{"selector": "...", "limit": 50}` | Multiple elements text |
| POST | `/element/html` | `{"selector": "..."}` | Element HTML |

### Interaction

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/click` | `{"selector": "...", "by_js": false}` | Click element |
| POST | `/type` | `{"selector": "...", "text": "...", "clear": true}` | Type into input |
| POST | `/press` | `{"key": "Enter"}` | Press a key |
| POST | `/scroll` | `{"delta_y": 500}` | Scroll page |
| POST | `/hover` | `{"selector": "..."}` | Hover over element |

### Waiting

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/wait/element` | `{"selector": "...", "timeout": 30, "state": "displayed"}` | Wait for element |
| POST | `/wait/text` | `{"text": "...", "timeout": 30}` | Wait for text on page |
| POST | `/wait/url` | `{"url": "...", "contains": true}` | Wait for URL change |
| POST | `/wait/time` | `{"seconds": 2}` | Simple delay |

### Visual

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/screenshot` | — | Full-page screenshot (returns base64 + path) |

### JavaScript

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/evaluate` | `{"script": "return document.title"}` | Run JS, get result |

### Cookies

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/cookies` | — | Get all cookies |
| POST | `/cookies/set` | `{"cookies": [{"name": "...", "value": "..."}]}` | Set cookies |
| POST | `/cookies/clear` | — | Clear all cookies |

### Tabs

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/browser/tabs` | — | List tab IDs |
| POST | `/browser/new-tab` | — | Open new tab |
| POST | `/browser/switch-tab` | `{"index": 0}` | Switch to tab |
| POST | `/browser/close-tab` | — | Close current tab |
| POST | `/browser/restart` | — | Restart browser |

## Workflow Tips

1. **Always start with `/snapshot`** after navigating — it gives you headings, buttons, inputs, and links
2. **Use `text:` selectors** for buttons and links (most reliable)
3. **Use `css:` selectors** for inputs (match by type, name, or placeholder)
4. **Wait after navigation** — use `/wait/element` or `/wait/text` before interacting
5. **Use `by_js: true`** on click/type if standard interaction fails
6. **Check `/status`** before starting — tells you if server is running

## When To Use This vs Built-in Browser

| Scenario | Use |
|----------|-----|
| Site blocks automation (X.com, LinkedIn, etc.) | **This skill** |
| Quick page read, no anti-bot issues | Built-in browser |
| Need persistent login sessions | **This skill** (keeps user-data dir) |
| Need to interact with complex JS apps | **This skill** |
| Simple screenshot or PDF | Built-in browser |
