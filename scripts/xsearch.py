#!/usr/bin/env python3
"""
Search X.com via DrissionPage browser server, scroll to collect tweets,
and write a markdown report.

Usage:
    python3 xsearch.py "openclaw since:2026-02-09"
    python3 xsearch.py "openclaw since:2026-02-09" --count 300
    python3 xsearch.py "openclaw since:2026-02-09" --count 300 --output /tmp/report.md
    python3 xsearch.py "openclaw since:2026-02-09" --tab live   # Latest instead of Top
"""

import argparse
import json
import os
import random
import time
from collections import Counter
from datetime import datetime, timezone

import requests

BASE = os.environ.get("DRISSION_URL", "http://127.0.0.1:18850")
DEFAULT_COUNT = 300
MAX_STALE_ROUNDS = 10


def api(method, path, body=None):
    url = f"{BASE}{path}"
    if method == "GET":
        r = requests.get(url, timeout=30)
    else:
        r = requests.post(url, json=body or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def human_pause(lo=1.5, hi=3.5):
    """Sleep a random human-like duration."""
    time.sleep(random.uniform(lo, hi))


def scroll_down(pixels=None):
    """Scroll by bringing the last visible tweet into view, then nudging further."""
    px = pixels or random.randint(600, 1200)
    # Blur any focused element to stop focus cycling
    api("POST", "/evaluate", {
        "script": "if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();"
    })
    # Scroll the last visible tweet into view (triggers X.com's virtual list to load more)
    api("POST", "/evaluate", {
        "script": f"""
        var articles = document.querySelectorAll('article[data-testid="tweet"]');
        if (articles.length > 0) {{
            articles[articles.length - 1].scrollIntoView({{behavior: 'smooth', block: 'start'}});
        }} else {{
            window.scrollTo(0, document.documentElement.scrollTop + {px});
        }}
        """
    })


def get_url():
    return api("GET", "/url").get("url", "")


# ---------------------------------------------------------------------------
# Tweet extraction — pure read-only JS, no element interaction
# ---------------------------------------------------------------------------

EXTRACT_JS = r"""
return (function() {
    var articles = document.querySelectorAll('article[data-testid="tweet"]');
    var tweets = [];
    for (var i = 0; i < articles.length; i++) {
        var a = articles[i];
        var userEl = a.querySelector('[data-testid="User-Name"]');
        var textEl = a.querySelector('[data-testid="tweetText"]');
        var timeEl = a.querySelector('time');

        var username = '', displayName = '';
        if (userEl) {
            var links = userEl.querySelectorAll('a[role="link"]');
            for (var j = 0; j < links.length; j++) {
                var href = links[j].getAttribute('href') || '';
                if (href.match(/^\/[A-Za-z0-9_]+$/)) {
                    username = '@' + href.slice(1);
                    break;
                }
            }
            var firstSpan = userEl.querySelector('span');
            if (firstSpan) displayName = firstSpan.textContent.trim();
        }

        var text = textEl ? textEl.innerText.trim() : '';
        var timestamp = timeEl ? timeEl.getAttribute('datetime') : '';

        var metrics = {};
        var group = a.querySelector('[role="group"]');
        if (group) {
            var labels = group.querySelectorAll('[data-testid]');
            for (var k = 0; k < labels.length; k++) {
                var tid = labels[k].getAttribute('data-testid');
                var val = labels[k].getAttribute('aria-label') || '';
                if (tid && val) metrics[tid] = val;
            }
        }

        if (text || username) {
            tweets.push({
                displayName: displayName,
                username: username,
                text: text,
                timestamp: timestamp,
                metrics: metrics
            });
        }
    }
    return JSON.stringify(tweets);
})()
"""


def extract_tweets():
    """Pull tweet data from visible DOM via read-only JS."""
    raw = api("POST", "/evaluate", {"script": EXTRACT_JS}).get("result", "[]")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    return raw if isinstance(raw, list) else []


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def collect(query, target, tab="top"):
    # Navigate to search — "top" is default (no f= param), "live" is Latest
    f_param = "" if tab == "top" else f"&f={tab}"
    search_url = (
        f"https://x.com/search?q={requests.utils.quote(query)}"
        f"&src=typed_query{f_param}"
    )
    print(f"[1/3] Navigating to search ({tab} tab): {query}")
    api("POST", "/navigate", {"url": search_url})
    human_pause(3, 5)

    url = get_url()
    print(f"  URL: {url}")

    # Fallback: if not on search page, use the search box
    if "search" not in url.lower() and "q=" not in url.lower():
        print("  Falling back to search box...")
        api("POST", "/click", {
            "selector": "css:input[data-testid='SearchBox_Search_Input']",
            "timeout": 5,
        })
        human_pause(0.8, 1.5)
        api("POST", "/type", {
            "selector": "css:input[data-testid='SearchBox_Search_Input']",
            "text": query, "clear": True,
        })
        human_pause(0.5, 1.0)
        api("POST", "/press", {"key": "Enter"})
        human_pause(3, 5)
        url = get_url()

    # Ensure correct tab
    if tab == "top" and "f=" in url:
        try:
            api("POST", "/click", {"selector": "text:Top", "timeout": 5})
            human_pause(2, 4)
        except Exception:
            pass
    elif tab == "live" and "f=live" not in url:
        try:
            api("POST", "/click", {"selector": "text:Latest", "timeout": 5})
            human_pause(2, 4)
        except Exception:
            pass

    # Defocus any element before starting collection (prevents focus cycling)
    api("POST", "/evaluate", {
        "script": "if (document.activeElement) document.activeElement.blur();"
    })

    # Wait for tweets to appear in the DOM before starting scroll loop
    print(f"[2/3] Waiting for tweets to load...")
    for _wait in range(10):
        initial = extract_tweets()
        if initial:
            print(f"  Found {len(initial)} tweets on initial load")
            break
        time.sleep(1)
    else:
        print("  WARNING: No tweets found after waiting — page may require login")

    # Scroll and collect
    print(f"  Collecting tweets (target: {target})...")
    all_tweets = []
    seen = set()
    stale = 0
    rnd = 0

    while len(all_tweets) < target and stale < MAX_STALE_ROUNDS:
        rnd += 1

        # Extract what's currently visible
        page_tweets = extract_tweets()
        new = 0
        for t in page_tweets:
            key = (t.get("username", ""), t.get("text", "")[:120])
            if key not in seen and key[1]:
                seen.add(key)
                all_tweets.append(t)
                new += 1

        print(f"  Round {rnd}: {len(page_tweets)} visible, {new} new — total {len(all_tweets)}")
        stale = stale + 1 if new == 0 else 0

        if len(all_tweets) >= target:
            break

        # Scroll down with JS and wait like a human
        scroll_down()
        human_pause(2.0, 4.0)

    print(f"  Done: {len(all_tweets)} tweets collected")
    return all_tweets


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report(query, tweets, path):
    print(f"[3/3] Writing report to {path}")
    users = Counter()
    daily = Counter()
    for t in tweets:
        users[t.get("username", "unknown")] += 1
        ts = t.get("timestamp", "")
        if ts:
            daily[ts[:10]] += 1

    lines = [
        "# X.com Search Report",
        f"**Query:** `{query}`",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Tweets collected:** {len(tweets)}",
        "",
        "## Summary",
        f"- Unique users: {len(users)}",
        f"- Date range: {min(daily) if daily else 'N/A'} to {max(daily) if daily else 'N/A'}",
        "",
    ]

    if daily:
        lines.append("## Volume by Day")
        for day in sorted(daily):
            lines.append(f"- {day}: {daily[day]} tweets")
        lines.append("")

    lines.append("## Top Users")
    for user, count in users.most_common(20):
        lines.append(f"- {user}: {count} tweets")
    lines.append("")

    lines.append("## Tweets")
    lines.append("")
    for i, t in enumerate(tweets, 1):
        name = t.get("displayName", "")
        user = t.get("username", "")
        text = t.get("text", "").replace("\n", " ")
        ts = t.get("timestamp", "")
        metrics = t.get("metrics", {})
        m_str = " | ".join(f"{k}: {v}" for k, v in metrics.items() if v and v != "0")

        lines.append(f"### {i}. {name} ({user}) — {ts}")
        lines.append(f"> {text}")
        if m_str:
            lines.append(f"*{m_str}*")
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"Report written: {path}")


def main():
    parser = argparse.ArgumentParser(description="Search X.com and generate a tweet report")
    parser.add_argument("query", help="Search query (e.g. 'openclaw since:2026-02-09')")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Target number of tweets")
    parser.add_argument("--tab", choices=["top", "live"], default="top",
                        help="Search tab: top (default) or live (latest)")
    parser.add_argument("--output", "-o",
                        help="Output file path (default: /tmp/xsearch_<date>.md)")
    args = parser.parse_args()

    if not args.output:
        today = datetime.now().strftime("%Y-%m-%d")
        args.output = f"/tmp/xsearch_{today}.md"

    tweets = collect(args.query, args.count, tab=args.tab)
    report(args.query, tweets, args.output)


if __name__ == "__main__":
    main()
