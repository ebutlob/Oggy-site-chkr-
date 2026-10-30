"""
╔══════════════════════════════════╗
║  🔍 OGGY SITE CHKR — SCRAPER    ║
╚══════════════════════════════════╝
Scrapes Google (via SerpAPI-style dorks + direct requests)
for Shopify stores matching a keyword, then verifies each one.
"""

import asyncio
import logging
import re
import random
import urllib.parse

import aiohttp

logger = logging.getLogger("OggyScraper")

# ─── User agents pool ───────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# ─── Google dork templates ───────────────────────────────
DORK_TEMPLATES = [
    '"{kw}" site:myshopify.com',
    'inurl:myshopify.com "{kw}"',
    '"{kw}" "powered by shopify"',
    '"{kw}" shopify checkout',
    'shopify store "{kw}" products',
    '"{kw}" inurl:collections/all',
    '"{kw}" site:shop.app',
]


def _make_google_url(query: str, start: int = 0) -> str:
    params = {
        "q":   query,
        "num": "10",
        "start": str(start),
        "hl": "en",
    }
    return "https://www.google.com/search?" + urllib.parse.urlencode(params)


def _extract_domains_from_google_html(html: str) -> list[str]:
    """Pull domains from Google result HTML."""
    domains = set()
    # Standard result links
    patterns = [
        r'href="https?://([a-zA-Z0-9\-]+\.myshopify\.com)[/"]',
        r'href="https?://((?:[a-zA-Z0-9\-]+\.)+[a-zA-Z]{2,})/(?:products|collections|cart)',
        r'"url":"https?://([a-zA-Z0-9\-\.]+)/products',
        r'data-url="https?://([a-zA-Z0-9\-\.]+)',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.IGNORECASE):
            d = m.group(1).lower().strip(".")
            if "google" in d or "youtube" in d or "facebook" in d:
                continue
            domains.add(d)

    # Also grab any .myshopify.com domains plainly
    for m in re.finditer(r'([a-zA-Z0-9\-]+\.myshopify\.com)', html):
        domains.add(m.group(1).lower())

    return list(domains)


async def _google_search(
    session: aiohttp.ClientSession,
    query: str,
    start: int = 0,
) -> list[str]:
    """Perform one Google search page and return discovered domains."""
    url = _make_google_url(query, start)
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
            ssl=False,
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            return _extract_domains_from_google_html(text)
    except Exception as e:
        logger.debug(f"Google search error: {e}")
        return []


async def _verify_shopify(
    domain: str,
    session: aiohttp.ClientSession,
) -> dict | None:
    """
    Verify a domain is Shopify, get lowest price & title.
    Returns dict or None.
    """
    domain = domain.strip().rstrip("/")
    if not domain.startswith("http"):
        base = "https://" + domain
    else:
        base = domain

    try:
        url = f"{base}/products.json?limit=50&sort_by=price-ascending"
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=False,
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                return None
            try:
                data = await resp.json(content_type=None)
            except Exception:
                return None

            products = data.get("products", [])
            if not products:
                return None

            prices = []
            best_title = ""
            for p in products:
                if not best_title:
                    best_title = p.get("title", "")
                for v in p.get("variants", []):
                    try:
                        prices.append(float(v["price"]))
                    except Exception:
                        pass

            if not prices:
                return None

            min_price = min(prices)
            site = base.replace("https://", "").replace("http://", "").split("/")[0]
            return {
                "site":  site,
                "price": min_price,
                "title": best_title[:60],
            }
    except Exception as e:
        logger.debug(f"Verify error {domain}: {e}")
        return None


async def search_google_for_shopify(
    keyword: str,
    want: int,
    on_progress=None,
    stop_ref: dict | None = None,
) -> list[dict]:
    """
    Main entry: search Google for Shopify sites matching `keyword`,
    verify each, return list of {site, price, title}.

    `on_progress(dict)` is called for each verified site.
    `stop_ref` is a dict with a "stop" key (set True to abort).
    """
    found: list[dict] = []
    seen_domains: set[str] = set()

    semaphore = asyncio.Semaphore(8)

    async with aiohttp.ClientSession() as session:

        # Build query list from multiple dork templates
        queries: list[str] = []
        for tpl in DORK_TEMPLATES:
            queries.append(tpl.replace("{kw}", keyword))
        # Add paginated variants for first 2 dorks
        for start in [10, 20, 30]:
            queries.append(DORK_TEMPLATES[0].replace("{kw}", keyword) + f"&start={start}")

        random.shuffle(queries)

        all_candidates: list[str] = []

        # Phase 1: Gather candidates from Google
        for query in queries:
            if stop_ref and stop_ref.get("stop"):
                break
            if len(all_candidates) > want * 5:
                break

            domains = await _google_search(session, query)
            for d in domains:
                if d not in seen_domains:
                    seen_domains.add(d)
                    all_candidates.append(d)

            # Polite delay
            await asyncio.sleep(random.uniform(1.5, 3.5))

        logger.info(f"Scraped {len(all_candidates)} candidates for '{keyword}'")

        # Phase 2: Verify candidates
        async def verify_one(domain: str):
            if stop_ref and stop_ref.get("stop"):
                return
            if len(found) >= want:
                return
            async with semaphore:
                result = await _verify_shopify(domain, session)
                if result and len(found) < want:
                    found.append(result)
                    if on_progress:
                        try:
                            await on_progress(result)
                        except Exception:
                            pass
                await asyncio.sleep(random.uniform(0.3, 0.8))

        tasks = [verify_one(d) for d in all_candidates]
        await asyncio.gather(*tasks)

    logger.info(f"Scrape complete: {len(found)} verified Shopify sites for '{keyword}'")
    return found[:want]
