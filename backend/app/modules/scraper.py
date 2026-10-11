"""Module 1 — page fetcher.

Fetches a URL asynchronously with HTTPX and parses the HTML into a plain dict
of machine-readable signals using BeautifulSoup.
"""

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .. import config


class ScrapeError(RuntimeError):
    """Raised on any HTTP or network failure while fetching a page."""


async def fetch_html(url: str) -> str:
    """Fetch raw HTML for ``url``.

    Uses browser-like headers, a 15s timeout, and follows redirects. Raises
    :class:`ScrapeError` on any failure — never returns ``None`` silently.
    """
    # Full browser-like header set. Many sites (CDNs like Akamai/Cloudflare)
    # return 403/502 to non-browser user-agents, so we mimic a real browser.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        async with httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (403, 401, 429, 503) or code == 502:
            raise ScrapeError(
                f"The site blocked automated access (HTTP {code}). This page "
                f"cannot be audited because its server refuses non-browser "
                f"requests. Try a different URL on the same brand's site."
            ) from exc
        raise ScrapeError(
            f"The page returned HTTP {code} and could not be fetched."
        ) from exc
    except httpx.TimeoutException as exc:
        raise ScrapeError(
            f"The page took too long to respond (timeout after "
            f"{config.HTTP_TIMEOUT_SECONDS}s)."
        ) from exc
    except httpx.HTTPError as exc:
        raise ScrapeError(f"Network error when fetching the page: {exc}") from exc


def _text_or_none(tag) -> Optional[str]:
    if tag is None:
        return None
    text = tag.get_text(strip=True)
    return text or None


def _extract_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, list):
            blocks.extend([b for b in parsed if isinstance(b, dict)])
        elif isinstance(parsed, dict):
            # Handle @graph containers.
            if "@graph" in parsed and isinstance(parsed["@graph"], list):
                blocks.extend([b for b in parsed["@graph"] if isinstance(b, dict)])
            else:
                blocks.append(parsed)
    return blocks


def _schema_types(blocks: List[Dict[str, Any]]) -> List[str]:
    types: List[str] = []
    for block in blocks:
        t = block.get("@type")
        if isinstance(t, list):
            types.extend([str(x) for x in t])
        elif t:
            types.append(str(t))
    # de-dupe, preserve order
    seen = set()
    out = []
    for t in types:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_html(html: str, base_url: str) -> Dict[str, Any]:
    """Parse HTML into a dict of signals used by the analyzer modules."""
    soup = BeautifulSoup(html, "lxml")

    # Title / meta description
    title = _text_or_none(soup.title)
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = (
        meta_desc_tag.get("content", "").strip() if meta_desc_tag else None
    ) or None

    # Canonical
    canonical_tag = soup.find("link", rel="canonical")
    canonical_url = canonical_tag.get("href").strip() if canonical_tag and canonical_tag.get("href") else None

    # Open Graph
    og_tags: Dict[str, str] = {}
    for tag in soup.find_all("meta", property=True):
        prop = tag.get("property", "")
        if prop.startswith("og:"):
            og_tags[prop] = tag.get("content", "")

    # Headings
    def heading_texts(level: str) -> List[str]:
        return [_text_or_none(h) or "" for h in soup.find_all(level)]

    headings = {
        "h1": heading_texts("h1"),
        "h2": heading_texts("h2"),
        "h3": heading_texts("h3"),
    }

    # JSON-LD structured data
    json_ld_blocks = _extract_json_ld(soup)
    schema_types = _schema_types(json_ld_blocks)

    # Images / alt-text coverage
    images = soup.find_all("img")
    total_images = len(images)
    images_with_alt = sum(1 for img in images if (img.get("alt") or "").strip())
    alt_coverage = (images_with_alt / total_images) if total_images else 1.0

    # Links (internal vs external)
    base_domain = urlparse(base_url).netloc
    internal_links = 0
    external_links = 0
    external_domains: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        netloc = urlparse(absolute).netloc
        if not netloc or netloc == base_domain:
            internal_links += 1
        else:
            external_links += 1
            if netloc not in external_domains:
                external_domains.append(netloc)

    # Word count from visible body text
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    body_text = soup.get_text(separator=" ", strip=True)
    word_count = len(body_text.split())

    return {
        "title": title,
        "meta_description": meta_description,
        "canonical_url": canonical_url,
        "og_tags": og_tags,
        "headings": headings,
        "json_ld_blocks": json_ld_blocks,
        "schema_types": schema_types,
        "total_images": total_images,
        "images_with_alt": images_with_alt,
        "alt_coverage": round(alt_coverage, 4),
        "internal_link_count": internal_links,
        "external_link_count": external_links,
        "external_domains": external_domains,
        "word_count": word_count,
        "body_text": body_text,
    }


async def scrape(url: str) -> Dict[str, Any]:
    """Fetch and parse a page. Raises :class:`ScrapeError` on fetch failure."""
    print(f"[scraper] fetching {url}")
    html = await fetch_html(url)
    parsed = parse_html(html, url)
    print(
        f"[scraper] parsed {url}: {parsed['word_count']} words, "
        f"{len(parsed['schema_types'])} schema types, "
        f"{parsed['total_images']} images"
    )
    return parsed
