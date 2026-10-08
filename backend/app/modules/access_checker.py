"""Module 2 — crawler access checker.

Fetches and parses robots.txt and llms.txt for the audited site, then
classifies a fixed panel of AI user-agents by category and whether they are
allowed to reach the audited path.

A 404 on either file is treated as "not found," not an error. All network
failures degrade gracefully.
"""

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from .. import config

# AI user-agents grouped by purpose. Blocking a *training* bot is materially
# different from blocking a *search/retrieval* bot — the scoring engine uses
# these categories to weight penalties.
BOT_CATEGORIES: Dict[str, List[str]] = {
    "training": ["GPTBot", "Google-Extended", "CCBot", "Bytespider"],
    "search": ["OAI-SearchBot", "PerplexityBot", "ClaudeBot"],
    "user": ["ChatGPT-User", "Claude-User"],
}


def _category_of(bot: str) -> str:
    for category, bots in BOT_CATEGORIES.items():
        if bot in bots:
            return category
    return "unknown"


def _base_url(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


def _audited_path(url: str) -> str:
    path = urlparse(url).path
    return path if path else "/"


async def _fetch_text(client: httpx.AsyncClient, url: str) -> Tuple[bool, Optional[str]]:
    """Return (found, raw_text). 404 => (False, None). Other errors => (False, None)."""
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        print(f"[access] fetch failed for {url}: {exc}")
        return False, None
    if resp.status_code == 200 and resp.text.strip():
        return True, resp.text
    return False, None


def parse_robots(raw: str) -> List[Dict[str, Any]]:
    """Parse robots.txt into a list of groups.

    Each group is ``{"agents": [...], "disallow": [...], "allow": [...]}``.
    """
    groups: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    last_line_was_agent = False

    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if current is None or not last_line_was_agent:
                current = {"agents": [], "disallow": [], "allow": []}
                groups.append(current)
            current["agents"].append(value)
            last_line_was_agent = True
        elif field == "disallow" and current is not None:
            current["disallow"].append(value)
            last_line_was_agent = False
        elif field == "allow" and current is not None:
            current["allow"].append(value)
            last_line_was_agent = False
        else:
            last_line_was_agent = False

    return groups


def _rules_for_agent(groups: List[Dict[str, Any]], agent: str) -> Optional[Dict[str, List[str]]]:
    """Return the most specific matching group for ``agent``.

    Exact user-agent match wins over the wildcard ``*`` group.
    """
    exact: Optional[Dict[str, Any]] = None
    wildcard: Optional[Dict[str, Any]] = None
    for group in groups:
        for a in group["agents"]:
            if a.lower() == agent.lower():
                exact = group
            elif a == "*":
                wildcard = group
    chosen = exact or wildcard
    if chosen is None:
        return None
    return {"disallow": chosen["disallow"], "allow": chosen["allow"]}


def _path_disallowed(rules: Optional[Dict[str, List[str]]], path: str) -> bool:
    """Determine whether ``path`` is disallowed under ``rules``.

    Uses longest-match precedence between Allow and Disallow directives, which
    matches the de-facto robots.txt standard.
    """
    if rules is None:
        return False

    def longest_match(patterns: List[str]) -> int:
        best = -1
        for pat in patterns:
            if pat == "":
                continue
            # "/" disallows everything.
            if pat == "/" or path.startswith(pat):
                best = max(best, len(pat))
        return best

    # A bare "Disallow:" (empty) explicitly allows all.
    if "" in rules["disallow"] and not any(p for p in rules["disallow"] if p):
        return False

    disallow_len = longest_match(rules["disallow"])
    allow_len = longest_match(rules["allow"])

    if disallow_len == -1:
        return False
    # Allow wins ties and longer matches.
    return disallow_len > allow_len


def classify_bots(robots_groups: List[Dict[str, Any]], audited_path: str) -> Dict[str, Dict[str, Any]]:
    """Build the bot-rules dict for every tracked user-agent."""
    result: Dict[str, Dict[str, Any]] = {}
    for category, bots in BOT_CATEGORIES.items():
        for bot in bots:
            rules = _rules_for_agent(robots_groups, bot)
            disallowed_root = _path_disallowed(rules, "/")
            disallowed_path = _path_disallowed(rules, audited_path)
            allowed = not (disallowed_root or disallowed_path)
            result[bot] = {
                "category": category,
                "allowed": allowed,
                "disallowed_on_root": disallowed_root,
                "disallowed_on_path": disallowed_path,
                "has_explicit_rule": rules is not None,
            }
    return result


async def check_access(url: str) -> Dict[str, Any]:
    """Fetch robots.txt + llms.txt and classify AI bot access.

    Never raises — always returns a dict, degrading gracefully on failure.
    """
    base = _base_url(url)
    path = _audited_path(url)
    print(f"[access] checking robots.txt / llms.txt for {base} (path={path})")

    headers = {"User-Agent": config.USER_AGENT}
    async with httpx.AsyncClient(
        timeout=config.HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:
        robots_found, robots_raw = await _fetch_text(client, f"{base}/robots.txt")
        llms_found, llms_raw = await _fetch_text(client, f"{base}/llms.txt")

    groups = parse_robots(robots_raw) if robots_found and robots_raw else []
    bot_rules = classify_bots(groups, path)

    blocked = [b for b, info in bot_rules.items() if not info["allowed"]]
    print(
        f"[access] robots_found={robots_found} llms_found={llms_found} "
        f"blocked_bots={blocked or 'none'}"
    )

    return {
        "robots_txt_found": robots_found,
        "robots_txt_raw": robots_raw,
        "llms_txt_found": llms_found,
        "llms_txt_raw": llms_raw,
        "bot_rules": bot_rules,
    }
