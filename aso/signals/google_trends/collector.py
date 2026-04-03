"""
Google Trends signal collector — three backends, one interface.

Backends (tried in order unless overridden):
  1. rss       — Free, no auth, ~0.2s, returns top 20 daily trending topics
  2. pytrends  — Free, no auth, scrapes Google Trends for specific keywords
  3. serpapi   — Paid ($25+/mo), API key, most reliable for production

Usage:
    collector = GoogleTrendsCollector(backend="rss")
    rows = collector.collect(keywords=[], country="us")
    collector.save_signals(rows)

    collector = GoogleTrendsCollector(backend="pytrends")
    rows = collector.collect(keywords=["pilates", "yoga app"], country="us")
    collector.save_signals(rows)

    collector = GoogleTrendsCollector(backend="serpapi", api_key="...")
    rows = collector.collect(keywords=["pilates"], country="us")
    collector.save_signals(rows)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone as tz

import requests

from aso.signals import register
from aso.signals.base import BaseSignalCollector

logger = logging.getLogger(__name__)


@register("google_trends")
class GoogleTrendsCollector(BaseSignalCollector):
    source_id = "google_trends"

    # Google Trends RSS geo codes are ISO-3166-1 alpha-2 uppercase
    _GEO_MAP = {
        "us": "US", "gb": "GB", "ca": "CA", "au": "AU", "de": "DE",
        "fr": "FR", "jp": "JP", "kr": "KR", "br": "BR", "in": "IN",
        "mx": "MX", "es": "ES", "it": "IT", "nl": "NL", "se": "SE",
        "no": "NO", "dk": "DK", "fi": "FI", "pl": "PL", "ru": "RU",
    }

    def __init__(self, backend: str = "rss", api_key: str | None = None):
        """
        backend: "rss", "pytrends", or "serpapi"
        api_key: required for serpapi, ignored for others.
                 Falls back to SERPAPI_API_KEY env var.
        """
        if backend not in ("rss", "pytrends", "serpapi"):
            raise ValueError(f"Unknown backend: {backend!r}")
        self.backend = backend
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY", "")

    def collect(self, keywords: list[str], country: str = "us") -> list[dict]:
        dispatch = {
            "rss": self._collect_rss,
            "pytrends": self._collect_pytrends,
            "serpapi": self._collect_serpapi,
        }
        return dispatch[self.backend](keywords, country)

    # ------------------------------------------------------------------
    # Backend 1: RSS (free, no auth, trending topics only)
    # ------------------------------------------------------------------

    def _collect_rss(self, keywords: list[str], country: str) -> list[dict]:
        """
        Fetch daily trending searches from Google Trends RSS feed.

        This does NOT accept keyword queries — it returns whatever is
        trending right now.  The *keywords* param is ignored (RSS returns
        the top ~20 trending topics for the given country).

        Returns list of dicts ready for save_signals().
        """
        geo = self._GEO_MAP.get(country.lower(), country.upper())
        url = f"https://trends.google.com/trending/rss?geo={geo}"

        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "RespectASO/1.0 (trend-signal-collector)",
        })
        resp.raise_for_status()

        return self._parse_rss_xml(resp.text, country)

    def _parse_rss_xml(self, xml_text: str, country: str) -> list[dict]:
        """Parse the Google Trends RSS XML into signal rows."""
        import xml.etree.ElementTree as ET

        rows = []
        today = date.today()

        root = ET.fromstring(xml_text)
        # RSS structure: <rss><channel><item>...</item></channel></rss>
        # Namespace for ht (Google Trends specific)
        ns = {"ht": "https://trends.google.com/trending/rss"}

        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is None or not title_el.text:
                continue

            keyword = title_el.text.strip()

            # ht:approx_traffic gives strings like "200K+", "1M+"
            traffic_el = item.find("ht:approx_traffic", ns)
            raw_volume = self._parse_traffic(
                traffic_el.text if traffic_el is not None else None
            )

            # Normalise: 1M+ = 1.0, 500K+ = 0.5, 200K+ = 0.2, etc.
            normalized = min(raw_volume / 1_000_000, 1.0) if raw_volume else None

            # Collect related news headlines
            news_items = []
            for news in item.findall("ht:news_item", ns):
                news_title = news.find("ht:news_item_title", ns)
                news_url = news.find("ht:news_item_url", ns)
                if news_title is not None and news_title.text:
                    news_items.append({
                        "title": news_title.text.strip(),
                        "url": news_url.text.strip() if news_url is not None and news_url.text else None,
                    })

            rows.append({
                "keyword": keyword,
                "raw_volume": raw_volume,
                "normalized_score": normalized,
                "country": country.lower(),
                "date_stamp": today,
                "metadata": {
                    "method": "rss",
                    "traffic_label": traffic_el.text.strip() if traffic_el is not None and traffic_el.text else None,
                    "news_items": news_items[:5],
                },
            })

        logger.info("[google_trends:rss] parsed %d trending topics for %s", len(rows), country)
        return rows

    @staticmethod
    def _parse_traffic(label: str | None) -> float | None:
        """Convert '200K+' / '2M+' to a numeric value."""
        if not label:
            return None
        label = label.strip().rstrip("+").replace(",", "")
        multiplier = 1
        if label.upper().endswith("K"):
            multiplier = 1_000
            label = label[:-1]
        elif label.upper().endswith("M"):
            multiplier = 1_000_000
            label = label[:-1]
        try:
            return float(label) * multiplier
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Backend 2: pytrends-modern (free, no auth, specific keywords)
    # ------------------------------------------------------------------

    def _collect_pytrends(self, keywords: list[str], country: str) -> list[dict]:
        """
        Use pytrends-modern to get interest-over-time for specific keywords.

        Requires: pip install pytrends-modern

        Google rate-limits aggressively — this backend adds delays between
        requests.  Best for small batches (1-5 keywords at a time).
        """
        try:
            from pytrends_modern import TrendReq, TrendsRSS
        except ImportError:
            raise ImportError(
                "pytrends-modern is not installed. Run:\n"
                "  pip install pytrends-modern\n"
                "Or use backend='rss' (no extra deps) or backend='serpapi'."
            )

        rows = []
        today = date.today()
        geo = self._GEO_MAP.get(country.lower(), country.upper())

        if not keywords:
            # No keywords given — fall back to RSS trending topics
            logger.info("[google_trends:pytrends] no keywords, falling back to RSS trends")
            rss = TrendsRSS()
            trends = rss.get_trends(geo=geo, output_format="dict")
            for trend in trends:
                raw = self._parse_traffic(trend.get("traffic"))
                rows.append({
                    "keyword": trend.get("title", ""),
                    "raw_volume": raw,
                    "normalized_score": min(raw / 1_000_000, 1.0) if raw else None,
                    "country": country.lower(),
                    "date_stamp": today,
                    "metadata": {
                        "method": "pytrends_rss",
                        "traffic_label": trend.get("traffic"),
                    },
                })
            return rows

        # Interest over time for specific keywords (batches of 5 max)
        pytrends = TrendReq(hl="en-US", tz=360)

        for i in range(0, len(keywords), 5):
            batch = keywords[i:i + 5]
            logger.info("[google_trends:pytrends] querying %s for %s", batch, geo)

            pytrends.build_payload(
                batch,
                cat=0,  # all categories (cat=31 = "Mobile Apps" but too narrow)
                timeframe="now 7-d",
                geo=geo,
            )

            df = pytrends.interest_over_time()
            if df.empty:
                logger.warning("[google_trends:pytrends] empty response for %s", batch)
                continue

            # df columns = keyword names, rows = timestamps
            for kw in batch:
                if kw not in df.columns:
                    continue
                series = df[kw]
                current_value = int(series.iloc[-1]) if len(series) > 0 else 0
                peak_value = int(series.max())

                rows.append({
                    "keyword": kw,
                    "raw_volume": float(current_value),
                    "normalized_score": current_value / 100.0,
                    "country": country.lower(),
                    "date_stamp": today,
                    "metadata": {
                        "method": "pytrends_interest_over_time",
                        "timeframe": "now 7-d",
                        "current_interest": current_value,
                        "peak_interest": peak_value,
                        "is_rising": current_value > int(series.median()),
                    },
                })

            # Rate-limit courtesy: sleep between batches
            if i + 5 < len(keywords):
                import time
                time.sleep(12)

        # Also fetch related queries for each keyword (rising = early signals)
        for kw in keywords:
            try:
                pytrends.build_payload([kw], timeframe="now 7-d", geo=geo)
                related = pytrends.related_queries()
                rising = related.get(kw, {}).get("rising")
                if rising is not None and not rising.empty:
                    # Add rising related queries as separate signal rows
                    for _, rq_row in rising.head(5).iterrows():
                        query_text = rq_row.get("query", "")
                        value = rq_row.get("value", 0)
                        rows.append({
                            "keyword": query_text,
                            "raw_volume": float(value),
                            "normalized_score": min(float(value) / 5000, 1.0),
                            "country": country.lower(),
                            "date_stamp": today,
                            "metadata": {
                                "method": "pytrends_related_rising",
                                "parent_keyword": kw,
                                "rise_pct": value,
                            },
                        })
                import time
                time.sleep(12)
            except Exception as exc:
                logger.warning("[google_trends:pytrends] related queries failed for %r: %s", kw, exc)

        return rows

    # ------------------------------------------------------------------
    # Backend 3: SerpAPI (paid, API key, most reliable)
    # ------------------------------------------------------------------

    def _collect_serpapi(self, keywords: list[str], country: str) -> list[dict]:
        """
        Use SerpAPI to get Google Trends data.

        Requires: pip install serpapi
        And a SERPAPI_API_KEY env var or api_key constructor arg.

        Pricing: $25/mo for 1,000 searches (cached searches are free).
        Sign up at https://serpapi.com
        """
        if not self.api_key:
            raise ValueError(
                "SerpAPI requires an API key. Set SERPAPI_API_KEY env var or pass api_key= to constructor.\n"
                "Sign up at https://serpapi.com (free tier: 250 searches/month)."
            )

        rows = []
        today = date.today()
        geo = self._GEO_MAP.get(country.lower(), country.upper())

        if not keywords:
            # Fetch currently trending searches
            rows.extend(self._serpapi_trending(geo, country))
        else:
            # Interest over time for specific keywords
            rows.extend(self._serpapi_interest(keywords, geo, country))

        return rows

    def _serpapi_trending(self, geo: str, country: str) -> list[dict]:
        """Fetch trending searches via SerpAPI."""
        params = {
            "engine": "google_trends_trending_now",
            "frequency": "daily",
            "geo": geo,
            "api_key": self.api_key,
        }
        resp = requests.get(
            "https://serpapi.com/search.json",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        rows = []
        today = date.today()
        daily_searches = data.get("daily_searches", [])
        for day in daily_searches:
            for search in day.get("searches", []):
                query_text = search.get("query", {}).get("text", "")
                traffic = search.get("search_volume", 0)
                rows.append({
                    "keyword": query_text,
                    "raw_volume": float(traffic) if traffic else None,
                    "normalized_score": min(float(traffic) / 1_000_000, 1.0) if traffic else None,
                    "country": country.lower(),
                    "date_stamp": today,
                    "metadata": {
                        "method": "serpapi_trending",
                        "traffic": traffic,
                    },
                })

        logger.info("[google_trends:serpapi] fetched %d trending topics for %s", len(rows), geo)
        return rows

    def _serpapi_interest(self, keywords: list[str], geo: str, country: str) -> list[dict]:
        """
        Fetch interest-over-time for specific keywords via SerpAPI.
        Max 5 keywords per request (Google Trends limit).
        """
        rows = []
        today = date.today()

        for i in range(0, len(keywords), 5):
            batch = keywords[i:i + 5]
            q = ",".join(batch)

            params = {
                "engine": "google_trends",
                "q": q,
                "data_type": "TIMESERIES",
                "date": "now 7-d",
                "geo": geo,
                "api_key": self.api_key,
            }
            resp = requests.get(
                "https://serpapi.com/search.json",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            iot = data.get("interest_over_time", {})
            timeline = iot.get("timeline_data", [])
            averages = {
                a["query"]: a.get("value", 0)
                for a in iot.get("averages", [])
            }

            for kw in batch:
                avg_value = averages.get(kw, 0)
                # Get most recent data point
                current = 0
                peak = 0
                if timeline:
                    for point in timeline:
                        for v in point.get("values", []):
                            if v.get("query") == kw:
                                val = v.get("extracted_value", 0)
                                peak = max(peak, val)
                    # Last point = most recent
                    last_point = timeline[-1]
                    for v in last_point.get("values", []):
                        if v.get("query") == kw:
                            current = v.get("extracted_value", 0)

                rows.append({
                    "keyword": kw,
                    "raw_volume": float(current),
                    "normalized_score": current / 100.0,
                    "country": country.lower(),
                    "date_stamp": today,
                    "metadata": {
                        "method": "serpapi_timeseries",
                        "timeframe": "now 7-d",
                        "current_interest": current,
                        "peak_interest": peak,
                        "average_interest": avg_value,
                        "is_rising": current > avg_value,
                    },
                })

            # Also get related queries (rising = early signals)
            for kw in batch:
                try:
                    rq_params = {
                        "engine": "google_trends",
                        "q": kw,
                        "data_type": "RELATED_QUERIES",
                        "date": "now 7-d",
                        "geo": geo,
                        "api_key": self.api_key,
                    }
                    rq_resp = requests.get(
                        "https://serpapi.com/search.json",
                        params=rq_params,
                        timeout=30,
                    )
                    rq_resp.raise_for_status()
                    rq_data = rq_resp.json()
                    rising = rq_data.get("related_queries", {}).get("rising", [])
                    for rq in rising[:5]:
                        query_text = rq.get("query", "")
                        value = rq.get("extracted_value", 0)
                        rows.append({
                            "keyword": query_text,
                            "raw_volume": float(value),
                            "normalized_score": min(float(value) / 5000, 1.0),
                            "country": country.lower(),
                            "date_stamp": today,
                            "metadata": {
                                "method": "serpapi_related_rising",
                                "parent_keyword": kw,
                                "rise_pct": value,
                            },
                        })
                except Exception as exc:
                    logger.warning("[google_trends:serpapi] related queries failed for %r: %s", kw, exc)

        logger.info("[google_trends:serpapi] fetched %d signals for %s", len(rows), geo)
        return rows
