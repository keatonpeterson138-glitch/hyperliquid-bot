"""
Breaking news & geopolitical event monitor.

Aggregates headlines from multiple free sources and scores them for
potential market impact so the bot can react (e.g. close positions,
reverse bias) before price catches up.

Sources (all free / no-API-key tier):
  • CryptoPanic API (free tier — crypto-specific)
  • RSS feeds: Reuters world, AP News, CNBC markets, Bloomberg politics
  • Truth Social / Trump posts via public Nitter-style RSS proxies
  • Twitter/X keyword search via RSSHub (self-hosted or public instances)

Each headline is scored:
  CRITICAL  – immediate position close / reversal (war, sanctions, black swan)
  HIGH      – large directional move expected (rate decision, regulation)
  MEDIUM    – moderate move, tighten stops
  LOW       – informational only
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Callable, Dict, List, Optional
from urllib.parse import quote_plus

import requests
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


# ── Impact severity ─────────────────────────────────────────────
class Impact(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# ── Single news item ────────────────────────────────────────────
@dataclass
class NewsItem:
    headline: str
    source: str
    url: str
    published: datetime
    impact: Impact = Impact.LOW
    sentiment: str = "neutral"      # "bearish" | "bullish" | "neutral"
    matched_keywords: list = field(default_factory=list)
    uid: str = ""

    def __post_init__(self):
        if not self.uid:
            raw = f"{self.headline}{self.source}{self.published.isoformat()}"
            self.uid = hashlib.md5(raw.encode()).hexdigest()


# ── Keyword → impact / sentiment mappings ────────────────────────

# CRITICAL bearish — close longs / open shorts immediately
CRITICAL_BEARISH = [
    r"\bbomb(s|ed|ing)?\b", r"\bwar\b", r"\binvasion\b", r"\bnuclear\b",
    r"\bsanction(s|ed)?\b", r"\bblack\s?swan\b", r"\bcrash(es|ed)?\b",
    r"\bdefault(s|ed)?\b", r"\bcollapse[ds]?\b", r"\bbank\s?run\b",
    r"\bterror(ist|ism)?\b", r"\bassassinat(e|ed|ion)\b",
    r"\bmarshall?\s+law\b", r"\bmartial\s+law\b",
    r"\bexchange\s+hack\b", r"\brug\s?pull\b",
    r"\bde-?peg\b", r"\binsolven(t|cy)\b",
    r"\biran\b.*\b(strike|attack|bomb|missile)\b",
    r"\b(strike|attack|bomb|missile)\b.*\biran\b",
    r"\bnorth\s+korea\b.*\b(launch|missile|nuclear)\b",
    r"\bchina\b.*\b(taiwan|invad|blockade)\b",
]

# HIGH bearish
HIGH_BEARISH = [
    r"\brate\s+hike\b", r"\bhawk(ish)?\b", r"\btaper(ing)?\b",
    r"\bban(s|ned)?\s+(crypto|bitcoin|trading)\b",
    r"\bsec\b.*\b(sue|charge|enforcement)\b",
    r"\bsubpoena\b", r"\bindictment\b",
    r"\bshutdown\b.*\b(government|exchange)\b",
    r"\brecession\b", r"\bdowngrade[ds]?\b",
    r"\bcpi\b.*\b(hot|high|surge)\b",
    r"\bunemployment\b.*\b(spike|surge|jump)\b",
    r"\btariff\b", r"\btrade\s+war\b",
]

# HIGH bullish
HIGH_BULLISH = [
    r"\brate\s+cut\b", r"\bdov(e|ish)\b",
    r"\betf\s+approv(al|ed)\b", r"\bspot\s+etf\b",
    r"\badopt(s|ed|ion)?\b.*\b(bitcoin|crypto)\b",
    r"\bstrategic\s+(bitcoin|crypto)\s+reserve\b",
    r"\bstimulus\b", r"\bqe\b", r"\beasin(g)?\b",
    r"\bpeace\s+(deal|agreement|talk)\b",
    r"\bcease\s?fire\b",
]

# MEDIUM
MEDIUM_BEARISH = [
    r"\bfed\b.*\b(minutes|statement|meeting)\b",
    r"\bregulat(ion|ory)\b", r"\bcrack\s?down\b",
    r"\bliquidat(e|ed|ion)\b", r"\bwhale\s+sell\b",
    r"\bdelist(ed|ing)?\b",
]

MEDIUM_BULLISH = [
    r"\bmicrostrategy\b.*\bbuy\b", r"\binstitutional\b.*\bbuy\b",
    r"\bwhale\s+buy\b", r"\baccumulat(e|ing|ion)\b",
    r"\ball[- ]time[- ]high\b", r"\bbullish\b",
    r"\bpartnership\b", r"\bintegrat(e|ion)\b",
]

# Trump-specific patterns (Truth Social / X posts)
TRUMP_PATTERNS = [
    (r"\btrump\b.*\b(executive\s+order|EO)\b", Impact.HIGH),
    (r"\btrump\b.*\b(tariff|sanction|ban)\b", Impact.HIGH),
    (r"\btrump\b.*\b(bitcoin|crypto)\b", Impact.HIGH),
    (r"\btrump\b.*\b(war|iran|china|russia|bomb)\b", Impact.CRITICAL),
    (r"\btruth\s*social\b", Impact.MEDIUM),
]


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_CRIT_BEAR = _compile_patterns(CRITICAL_BEARISH)
_HIGH_BEAR = _compile_patterns(HIGH_BEARISH)
_HIGH_BULL = _compile_patterns(HIGH_BULLISH)
_MED_BEAR  = _compile_patterns(MEDIUM_BEARISH)
_MED_BULL  = _compile_patterns(MEDIUM_BULLISH)
_TRUMP     = [(re.compile(p, re.IGNORECASE), imp) for p, imp in TRUMP_PATTERNS]


def score_headline(text: str) -> tuple[Impact, str, list[str]]:
    """Score a headline string. Returns (impact, sentiment, matched_keywords)."""
    matched = []

    for pat in _CRIT_BEAR:
        if pat.search(text):
            matched.append(pat.pattern)
            return Impact.CRITICAL, "bearish", matched

    for pat in _HIGH_BEAR:
        if pat.search(text):
            matched.append(pat.pattern)
            return Impact.HIGH, "bearish", matched

    for pat in _HIGH_BULL:
        if pat.search(text):
            matched.append(pat.pattern)
            return Impact.HIGH, "bullish", matched

    for pat, imp in _TRUMP:
        if pat.search(text):
            matched.append(pat.pattern)
            return imp, "bearish", matched  # default bearish for Trump volatility

    for pat in _MED_BEAR:
        if pat.search(text):
            matched.append(pat.pattern)
            return Impact.MEDIUM, "bearish", matched

    for pat in _MED_BULL:
        if pat.search(text):
            matched.append(pat.pattern)
            return Impact.MEDIUM, "bullish", matched

    return Impact.LOW, "neutral", []


# ── RSS feed parser ──────────────────────────────────────────────
def _parse_rss(url: str, source_name: str, timeout: int = 10) -> list[NewsItem]:
    """Fetch and parse an RSS/Atom feed into NewsItem list."""
    items: list[NewsItem] = []
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "HyperliquidBot/1.0"
        })
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        # Handle both RSS 2.0 (<item>) and Atom (<entry>)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall(".//item") or root.findall(".//atom:entry", ns)

        for entry in entries[:30]:  # cap per source
            title_el = entry.find("title") or entry.find("atom:title", ns)
            link_el  = entry.find("link")  or entry.find("atom:link", ns)
            pub_el   = entry.find("pubDate") or entry.find("atom:published", ns) or entry.find("atom:updated", ns)

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            if not title:
                continue

            link = ""
            if link_el is not None:
                link = link_el.text or link_el.get("href", "")

            pub_dt = datetime.now(timezone.utc)
            if pub_el is not None and pub_el.text:
                try:
                    # Try common RSS date formats
                    for fmt in ("%a, %d %b %Y %H:%M:%S %z",
                                "%a, %d %b %Y %H:%M:%S GMT",
                                "%Y-%m-%dT%H:%M:%S%z",
                                "%Y-%m-%dT%H:%M:%SZ"):
                        try:
                            pub_dt = datetime.strptime(pub_el.text.strip(), fmt)
                            if pub_dt.tzinfo is None:
                                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass

            impact, sentiment, kw = score_headline(title)
            items.append(NewsItem(
                headline=title,
                source=source_name,
                url=link.strip(),
                published=pub_dt,
                impact=impact,
                sentiment=sentiment,
                matched_keywords=kw,
            ))
    except Exception as e:
        logger.warning(f"Failed to fetch RSS from {source_name}: {e}")

    return items


# ── CryptoPanic (free tier, no key needed for basic) ─────────────
def _fetch_cryptopanic(api_key: str = "") -> list[NewsItem]:
    """Fetch from CryptoPanic API (free tier)."""
    items: list[NewsItem] = []
    try:
        url = "https://cryptopanic.com/api/free/v1/posts/"
        params = {"auth_token": api_key} if api_key else {}
        params["kind"] = "news"
        params["filter"] = "important"

        resp = requests.get(url, params=params, timeout=10, headers={
            "User-Agent": "HyperliquidBot/1.0"
        })
        if resp.status_code == 200:
            data = resp.json()
            for post in data.get("results", [])[:25]:
                title = post.get("title", "")
                if not title:
                    continue
                pub_str = post.get("published_at", "")
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pub_dt = datetime.now(timezone.utc)

                impact, sentiment, kw = score_headline(title)

                # CryptoPanic has its own sentiment
                cp_sentiment = post.get("votes", {})
                if cp_sentiment.get("negative", 0) > cp_sentiment.get("positive", 0):
                    if sentiment == "neutral":
                        sentiment = "bearish"
                elif cp_sentiment.get("positive", 0) > cp_sentiment.get("negative", 0):
                    if sentiment == "neutral":
                        sentiment = "bullish"

                items.append(NewsItem(
                    headline=title,
                    source="CryptoPanic",
                    url=post.get("url", ""),
                    published=pub_dt,
                    impact=impact,
                    sentiment=sentiment,
                    matched_keywords=kw,
                ))
    except Exception as e:
        logger.warning(f"CryptoPanic fetch failed: {e}")
    return items


# ── Feed registry ────────────────────────────────────────────────
DEFAULT_RSS_FEEDS: list[tuple[str, str]] = [
    # (URL, Source name)
    ("https://feeds.reuters.com/reuters/worldNews", "Reuters World"),
    ("https://feeds.reuters.com/reuters/businessNews", "Reuters Business"),
    ("https://rss.app/feeds/v1.1/cnbc-markets.xml", "CNBC Markets"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
    ("https://cointelegraph.com/rss", "CoinTelegraph"),
    ("https://news.google.com/rss/search?q=bitcoin+OR+crypto+OR+geopolitical&hl=en-US&gl=US&ceid=US:en", "Google News Crypto"),
    ("https://news.google.com/rss/search?q=trump+tariff+OR+sanction+OR+executive+order&hl=en-US&gl=US&ceid=US:en", "Google News Trump"),
    ("https://news.google.com/rss/search?q=iran+OR+china+taiwan+OR+war+OR+missile&hl=en-US&gl=US&ceid=US:en", "Google News Geopolitical"),
    ("https://nitter.privacydev.net/realDonaldTrump/rss", "Trump (Nitter)"),
    ("https://rsshub.app/twitter/user/realDonaldTrump", "Trump (RSSHub)"),
]


# ── Main monitor class ──────────────────────────────────────────
class NewsMonitor:
    """
    Background news aggregator that polls multiple sources and fires
    callbacks when high-impact events are detected.

    Usage:
        monitor = NewsMonitor()
        monitor.on_critical = lambda item: print("ALERT!", item.headline)
        monitor.start()
    """

    def __init__(
        self,
        poll_interval: int = 60,
        cryptopanic_key: str = "",
        extra_feeds: list[tuple[str, str]] | None = None,
        custom_keywords: list[tuple[str, Impact, str]] | None = None,
    ):
        self.poll_interval = poll_interval
        self.cryptopanic_key = cryptopanic_key
        self.feeds = list(DEFAULT_RSS_FEEDS)
        if extra_feeds:
            self.feeds.extend(extra_feeds)

        # Custom keyword rules: (regex_pattern, Impact, sentiment)
        self._custom_rules: list[tuple[re.Pattern, Impact, str]] = []
        if custom_keywords:
            for pat, imp, sent in custom_keywords:
                self._custom_rules.append((re.compile(pat, re.IGNORECASE), imp, sent))

        # State
        self._seen: set[str] = set()      # uid dedup
        self._items: list[NewsItem] = []   # all items (newest first)
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Callbacks
        self.on_news: Optional[Callable[[NewsItem], None]] = None        # every new item
        self.on_high: Optional[Callable[[NewsItem], None]] = None        # HIGH+
        self.on_critical: Optional[Callable[[NewsItem], None]] = None    # CRITICAL only

    # ── Custom keyword re-scoring ────────────────────────────────
    def _apply_custom_rules(self, item: NewsItem) -> NewsItem:
        for pat, imp, sent in self._custom_rules:
            if pat.search(item.headline):
                if imp > item.impact:
                    item.impact = imp
                    item.sentiment = sent
                    item.matched_keywords.append(f"custom:{pat.pattern}")
        return item

    # ── Polling ──────────────────────────────────────────────────
    def _poll_once(self):
        """Single polling cycle across all sources."""
        all_items: list[NewsItem] = []

        # RSS feeds (parallel would be faster but kept simple)
        for url, name in self.feeds:
            fetched = _parse_rss(url, name, timeout=8)
            all_items.extend(fetched)

        # CryptoPanic
        cp_items = _fetch_cryptopanic(self.cryptopanic_key)
        all_items.extend(cp_items)

        # Process new items
        new_count = 0
        for item in all_items:
            if item.uid in self._seen:
                continue

            # Apply custom rules
            item = self._apply_custom_rules(item)

            # Only keep items from last 24 hours
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            item_time = item.published
            if item_time.tzinfo is None:
                item_time = item_time.replace(tzinfo=timezone.utc)
            if item_time < cutoff:
                continue

            self._seen.add(item.uid)
            new_count += 1

            with self._lock:
                self._items.insert(0, item)
                # Cap stored items
                if len(self._items) > 500:
                    self._items = self._items[:500]

            # Fire callbacks
            try:
                if self.on_news:
                    self.on_news(item)
                if item.impact >= Impact.HIGH and self.on_high:
                    self.on_high(item)
                if item.impact >= Impact.CRITICAL and self.on_critical:
                    self.on_critical(item)
            except Exception as e:
                logger.error(f"News callback error: {e}")

        if new_count:
            logger.info(f"News monitor: {new_count} new items from {len(self.feeds)+1} sources")

    def _loop(self):
        """Background polling loop."""
        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                logger.error(f"News monitor poll error: {e}")
            # Sleep in small increments so stop() is responsive
            for _ in range(self.poll_interval):
                if not self._running:
                    break
                time.sleep(1)

    # ── Public API ───────────────────────────────────────────────
    def start(self):
        """Start background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="news-monitor")
        self._thread.start()
        logger.info(f"News monitor started (poll every {self.poll_interval}s, {len(self.feeds)} feeds)")

    def stop(self):
        """Stop polling."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("News monitor stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_items(self, limit: int = 100, min_impact: Impact = Impact.LOW) -> list[NewsItem]:
        """Return recent news items, newest first."""
        with self._lock:
            filtered = [i for i in self._items if i.impact >= min_impact]
            return filtered[:limit]

    def get_critical_items(self, since_minutes: int = 5) -> list[NewsItem]:
        """Get CRITICAL items from the last N minutes."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        with self._lock:
            return [
                i for i in self._items
                if i.impact >= Impact.CRITICAL
                and (i.published.replace(tzinfo=timezone.utc) if i.published.tzinfo is None else i.published) >= cutoff
            ]

    def get_sentiment_bias(self, window_minutes: int = 30) -> str:
        """
        Aggregate sentiment from recent high-impact news.
        Returns 'bearish', 'bullish', or 'neutral'.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        with self._lock:
            recent = [
                i for i in self._items
                if i.impact >= Impact.MEDIUM
                and (i.published.replace(tzinfo=timezone.utc) if i.published.tzinfo is None else i.published) >= cutoff
            ]

        if not recent:
            return "neutral"

        # Weight by impact level
        bull_score = sum(i.impact for i in recent if i.sentiment == "bullish")
        bear_score = sum(i.impact for i in recent if i.sentiment == "bearish")

        if bear_score > bull_score * 1.5:
            return "bearish"
        elif bull_score > bear_score * 1.5:
            return "bullish"
        return "neutral"

    def add_custom_keyword(self, pattern: str, impact: Impact, sentiment: str):
        """Add a runtime keyword rule."""
        self._custom_rules.append((re.compile(pattern, re.IGNORECASE), impact, sentiment))
        logger.info(f"Added custom news keyword: '{pattern}' → {impact.name} {sentiment}")
