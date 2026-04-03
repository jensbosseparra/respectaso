---
title: "Trend Signal Integration Roadmap"
description: "Modular architecture for 17 external trend data sources to detect emerging iOS App Store keyword demand"
version: "1.0.0"
created: "2026-03-29"
priority_order:
  - google_trends
  - x_twitter
  - reddit
  - product_hunt
  - hacker_news
  - gdelt_news
  - wikipedia_pageviews
  - youtube
  - app_store_native
  - tiktok
  - bluesky
  - mastodon
  - github_trending
  - steam
  - podcast_index
  - newsapi
  - paid_aso_providers
architecture: "self-contained modules with shared signal bus"
database: "SQLite (same as main app)"
timestamp_strategy: "UTC ISO-8601 with first_seen_at tracking"
---

# Trend Signal Integration Roadmap

## Architecture Overview

Each signal source is a **self-contained module** in its own folder under
`aso/signals/`. Modules are independent — they duplicate shared patterns (HTTP
clients, DB helpers) intentionally so that adding, removing, or disabling a
module never breaks another. Every module writes to a shared `TrendSignal` table
with a UTC timestamp and a `first_seen_at` field for tracking when a term first
appeared across any source.

```
aso/
  signals/
    __init__.py                 # Signal registry, shared TrendSignal model
    base.py                     # BaseSignalCollector ABC + shared schema
    google_trends/
      __init__.py
      collector.py              # GoogleTrendsCollector
      requirements.txt          # Module-specific deps
      README.md                 # Setup instructions
    x_twitter/
      __init__.py
      collector.py
      requirements.txt
      README.md
    reddit/
      ...
    product_hunt/
      ...
    (one folder per source)
```

### Shared Database Schema

```sql
CREATE TABLE aso_trendsignal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          VARCHAR(50) NOT NULL,          -- e.g. "google_trends", "reddit"
    keyword         VARCHAR(500) NOT NULL,         -- the trending term/topic
    raw_volume      REAL,                          -- source-specific metric (views, mentions, score)
    normalized_score REAL,                         -- 0.0-1.0 normalized intensity
    country         VARCHAR(5) DEFAULT 'us',       -- ISO country code
    metadata        JSON,                          -- source-specific extra data
    first_seen_at   DATETIME NOT NULL,             -- UTC: when this keyword FIRST appeared in ANY source
    collected_at    DATETIME NOT NULL,             -- UTC: when this data point was collected
    date_stamp      DATE NOT NULL,                 -- UTC date for daily aggregation
    UNIQUE(source, keyword, country, date_stamp)
);

CREATE INDEX idx_trendsignal_keyword ON aso_trendsignal(keyword);
CREATE INDEX idx_trendsignal_first_seen ON aso_trendsignal(first_seen_at);
CREATE INDEX idx_trendsignal_source_date ON aso_trendsignal(source, date_stamp);
```

### Correlation Detection

```sql
-- Find keywords appearing in 2+ sources within a 48-hour window
SELECT keyword, COUNT(DISTINCT source) as source_count,
       MIN(first_seen_at) as earliest_signal,
       GROUP_CONCAT(DISTINCT source) as sources
FROM aso_trendsignal
WHERE collected_at > datetime('now', '-48 hours')
GROUP BY keyword
HAVING source_count >= 2
ORDER BY source_count DESC, earliest_signal ASC;
```

### Timestamp Strategy

Every data point records:
- **`first_seen_at`**: The first time this keyword appeared in ANY signal source.
  On insert, check if the keyword already exists in the table; if so, reuse the
  earliest `first_seen_at`. This is the "popping off" moment.
- **`collected_at`**: The exact UTC datetime when the collector fetched this data
  point. This is the collection timestamp.
- **`date_stamp`**: The UTC date (no time) for daily deduplication and aggregation.

This lets you answer: "When did 'OpenClaw' first appear anywhere?" and "How did
it spread across sources over the following hours/days?"

---

## Module 1: Google Trends (PRIORITY 1 — Test First)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `google_trends` |
| Cost | Free (RSS/scraping) or $25+/mo (SerpAPI) |
| Freshness | Real-time trending = minutes; Interest over time = 1-3 days |
| Auth | None for RSS; API key for SerpAPI; Application for official alpha |
| Rate Limits | RSS: unlimited; pytrends-modern: ~10 req/min; SerpAPI: 50-6000/hr by plan |
| Signal Type | Early-to-mid (search interest = direct demand proxy) |

### API Documentation

| Resource | URL |
|----------|-----|
| Official Google Trends API (alpha, July 2025) | https://developers.google.com/search/apis/trends |
| Official API announcement | https://developers.google.com/search/blog/2025/07/trends-api |
| Google Trends RSS feed (free, stable) | `https://trends.google.com/trending/rss?geo=US` |
| SerpAPI Google Trends docs | https://serpapi.com/google-trends-api |
| SerpAPI pricing | https://serpapi.com/pricing |

### Python Libraries

| Library | Status | PyPI | GitHub |
|---------|--------|------|--------|
| `pytrends` | **DEAD** — archived April 2025 | https://pypi.org/project/pytrends/ | https://github.com/GeneralMills/pytrends (archived) |
| `pytrends-modern` | **Active** — latest release March 2026 | https://pypi.org/project/pytrends-modern/ | https://github.com/yiromo/pytrends-modern |
| `trendspyg` | **Active** — latest release Jan 2026 | https://pypi.org/project/trendspyg/ | https://github.com/flack0x/trendspyg |
| `trendspy` | Stale — last release Dec 2024 | https://pypi.org/project/trendspy/ | https://github.com/sdil87/trendspy |
| `serpapi` (SerpAPI client) | Active | https://pypi.org/project/serpapi/ | https://github.com/serpapi/serpapi-python |

### MCP Servers

| Server | GitHub | Auth Required |
|--------|--------|---------------|
| google-news-trends-mcp (jmanek) — RSS-based, no API key | https://github.com/jmanek/google-news-trends-mcp | No |
| google-trends-mcp (andrewlwn77) — RapidAPI key needed | https://github.com/andrewlwn77/google-trends-mcp | Yes |
| GoogleTrendsMCP (cryptoken) | https://github.com/cryptoken/GoogleTrendsMCP | Varies |
| Trends MCP (multi-source) | https://glama.ai/mcp/servers/trendsmcp/trends-mcp | Varies |

### Module Dependencies (`google_trends/requirements.txt`)

```
pytrends-modern>=0.2.5
serpapi>=1.0.0          # optional: paid, reliable alternative
requests>=2.32.0
```

### Implementation Plan

1. **Primary method**: Parse Google Trends RSS feed (`https://trends.google.com/trending/rss?geo={country}`) — free, stable, no auth, returns top 10-20 daily trending topics with approximate traffic counts
2. **Secondary method**: `pytrends-modern` for `interest_over_time()` on specific keywords (category 31 = "Mobile Apps"), with proxy rotation and 10-15 second delays between requests
3. **Reliable fallback**: SerpAPI ($25/mo for 1,000 searches) if scraping is too fragile
4. **Future**: Apply for official Google Trends API alpha at https://developers.google.com/search/apis/trends

### Data Collected

```python
{
    "source": "google_trends",
    "keyword": "openclaw app",
    "raw_volume": 85,              # Google's 0-100 relative interest score
    "normalized_score": 0.85,      # raw_volume / 100
    "country": "us",
    "metadata": {
        "method": "rss|pytrends|serpapi",
        "related_queries": ["openclaw ios", "openclaw download"],
        "category": "Mobile Apps",
        "traffic_estimate": "50K+", # from RSS only
    },
    "first_seen_at": "2026-03-29T14:30:00Z",
    "collected_at": "2026-03-29T15:00:00Z",
    "date_stamp": "2026-03-29"
}
```

### Correlation Metrics

- Google Trends interest 0-100 → direct proxy for search demand
- Rising/breakout queries → early signal for new keywords
- Category-filtered interest (cat=31) → app-specific trends
- Cross-reference: if a keyword spikes in Google Trends AND appears in Reddit/HN → high-confidence emerging trend

---

## Module 2: X / Twitter API (PRIORITY 2)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `x_twitter` |
| Cost | Pay-per-use: $0.005/post read, $0.010/post create, $0.015/interaction |
| Freshness | Real-time |
| Auth | OAuth 2.0 Bearer Token or App-only auth |
| Rate Limits | 2M post reads/month cap; per-endpoint rate limits apply |
| Signal Type | Early (social buzz precedes search by hours-days) |

### Pricing (Pay-Per-Use, launched February 2026)

X killed the old subscription tiers (Basic $200/mo, Pro $5,000/mo) in January
2026 and moved to pay-per-use credits.

| Operation | Cost per Request |
|-----------|-----------------|
| Post read (fetch tweet) | $0.005 |
| Post create (write tweet) | $0.010 |
| User profile lookup | $0.010 |
| DM event read | $0.010 |
| DM interaction create | $0.015 |
| User interaction (follow, like, retweet) | $0.015 |

**Key rules**:
- Purchase credits upfront in the Developer Console
- 24-hour UTC deduplication: same resource fetched twice in a day = 1 charge
- Monthly cap: 2M post reads. Beyond that → Enterprise ($42K+/mo)
- Spending $200+/month earns 10-20% back as xAI API credits
- Legacy Free tier users get a one-time $10 voucher
- Basic & Pro plans still available for existing users but new signups are pay-per-use

**Cost examples**:
- 10,000 post reads/month = **$50**
- 50,000 post reads/month = **$250**
- 100,000 post reads/month = **$500**

### API Documentation

| Resource | URL |
|----------|-----|
| Official X API pricing | https://docs.x.com/x-api/getting-started/pricing |
| Pay-per-use announcement | https://devcommunity.x.com/t/announcing-the-launch-of-x-api-pay-per-use-pricing/256476 |
| API v2 documentation | https://docs.x.com/x-api |
| Tweet counts endpoint | https://docs.x.com/x-api/posts/post-counts/api-reference |
| Search endpoint | https://docs.x.com/x-api/posts/search/api-reference |
| Developer portal | https://developer.x.com |

### Python Libraries

| Library | PyPI |
|---------|------|
| `tweepy` | https://pypi.org/project/tweepy/ |
| `python-twitter-v2` | https://pypi.org/project/python-twitter-v2/ |

### Module Dependencies (`x_twitter/requirements.txt`)

```
tweepy>=4.14.0
requests>=2.32.0
```

### Implementation Plan

1. **Primary method**: Tweet counts endpoint (`/2/tweets/counts/recent`) — returns volume per query in minute/hour/day buckets over 7 days. Does NOT consume post read quota (only credits).
2. **Queries**: Monitor app-related hashtags, app names, and trending keywords. Example: `"openclaw" OR #openclaw -is:retweet lang:en`
3. **Volume spike detection**: Compare current hour's count against 7-day rolling average. Flag 3x+ spikes.
4. **Budget strategy**: Start with $50/month (10K reads). Use counts endpoint for volume tracking (cheaper than fetching full tweets). Only fetch full tweets for context when a spike is detected.

### Cheaper Alternatives

| Service | Cost/mo | Trade-off |
|---------|---------|-----------|
| Brand24 | $79-$399 | Social listening with X coverage, alerts |
| SocialData.tools | $49-$290 | Unofficial X scraping (ToS risk) |

---

## Module 3: Reddit (PRIORITY 3)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `reddit` |
| Cost | Free (non-commercial) or $0.24/1K requests (commercial) |
| Freshness | Real-time (seconds to minutes) |
| Auth | OAuth2 required (apply at reddit.com/prefs/apps) |
| Rate Limits | 100 req/min (OAuth) |
| Signal Type | Early (early adopter discussions precede mainstream by days) |

### API Documentation

| Resource | URL |
|----------|-----|
| Reddit API docs | https://www.reddit.com/dev/api/ |
| Reddit Data API wiki | https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki |
| PRAW docs | https://praw.readthedocs.io/en/stable/ |
| PRAW PyPI | https://pypi.org/project/praw/ |

### MCP Servers

| Server | GitHub |
|--------|--------|
| reddit-mcp-server (eliasbiondo) — zero-config | https://github.com/eliasbiondo/reddit-mcp-server |
| reddit-mcp (Arindam200) | https://github.com/Arindam200/reddit-mcp |
| mcp-server-reddit (Hawstein) | https://github.com/Hawstein/mcp-server-reddit |

### Module Dependencies (`reddit/requirements.txt`)

```
praw>=7.8.1
```

### Implementation Plan

1. **Monitor subreddits**: r/apps, r/iosapps, r/iphone, r/apple, r/productivity, r/gaming, r/androidapps
2. **Track keyword velocity**: Search posts/comments by keyword, count mentions per hour/day
3. **Free RSS fallback**: `https://www.reddit.com/r/{sub}/search.json?q={keyword}&sort=new&t=day` (no auth needed for JSON endpoints, lower rate limits)
4. **Spike detection**: Flag keywords with 5x+ their weekly average mention rate

---

## Module 4: Product Hunt (PRIORITY 4)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `product_hunt` |
| Cost | Free |
| Freshness | Real-time |
| Auth | OAuth2 Bearer token (register at producthunt.com) |
| Rate Limits | Complexity-based GraphQL limits |
| Signal Type | Early (product launches precede App Store spikes by 24-72 hours) |

### API Documentation

| Resource | URL |
|----------|-----|
| Product Hunt API v2 docs | https://api.producthunt.com/v2/docs |
| GraphQL reference | http://api-v2-docs.producthunt.com.s3-website-us-east-1.amazonaws.com/operation/query/ |
| API explorer (GraphiQL) | https://ph-graph-api-explorer.herokuapp.com/ |
| Python library | https://pypi.org/project/producthunt-api/ |

### Module Dependencies (`product_hunt/requirements.txt`)

```
requests>=2.32.0
```

### Implementation Plan

1. **Daily poll**: Fetch top 20 posts, filter by iOS/mobile/productivity topics
2. **Track upvote velocity**: Products with 100+ upvotes in first 4 hours = trending
3. **Extract app names**: Parse product names and URLs for App Store links
4. **Cross-reference**: Match Product Hunt launches to iTunes Search results

---

## Module 5: Hacker News (PRIORITY 5)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `hacker_news` |
| Cost | Free |
| Freshness | Real-time (Algolia indexes within minutes) |
| Auth | None |
| Rate Limits | Generous (undocumented) |
| Signal Type | Early (tech community signal, strong for dev tools) |

### API Documentation

| Resource | URL |
|----------|-----|
| HN Algolia API docs | https://hn.algolia.com/api |
| HN Algolia GitHub | https://github.com/algolia/hn-search |
| HN Firebase API | https://github.com/HackerNews/API |

### Module Dependencies (`hacker_news/requirements.txt`)

```
requests>=2.32.0
```

### Implementation Plan

1. **Search by keyword**: `GET https://hn.algolia.com/api/v1/search?query={keyword}&tags=story`
2. **Track front page**: Monitor `/v0/topstories.json` for app-related stories
3. **Score threshold**: Stories with 50+ points within 2 hours = trending signal
4. **Comment velocity**: High comment count relative to score = controversial/interesting topic

---

## Module 6: GDELT News (PRIORITY 6)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `gdelt_news` |
| Cost | Free |
| Freshness | 15 minutes |
| Auth | None |
| Rate Limits | Moderate (undocumented, covers 3-month rolling window) |
| Signal Type | Mid (mainstream news coverage = growing awareness) |

### API Documentation

| Resource | URL |
|----------|-----|
| GDELT DOC 2.0 API | https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ |
| gdeltdoc Python library | https://pypi.org/project/gdeltdoc/ |
| gdeltPyR Python library | https://pypi.org/project/gdelt/ |
| gdeltPyR docs | https://linwoodc3.github.io/gdeltPyR/ |

### Module Dependencies (`gdelt_news/requirements.txt`)

```
gdeltdoc>=1.4.0
```

### Implementation Plan

1. **Article volume timeline**: `mode=TimelineVol` for keyword volume over time
2. **Article list**: `mode=ArtList` to get actual article URLs and sources
3. **15-minute polling**: Match GDELT's update frequency
4. **Spike detection**: Compare current 15-min volume against 7-day rolling average

---

## Module 7: Wikipedia Pageviews (PRIORITY 7)

### Overview

Wikipedia Pageviews tracks the exact number of times any Wikipedia article was
viewed, broken down by day or hour, by access type (desktop, mobile-web,
mobile-app), and by user type (human vs bot). Data available from July 2015.

**Why it matters**: When people start looking up an app on Wikipedia, it has
crossed from niche to mainstream. A spike from 50 views/day to 50,000 views/day
is an unmistakable signal that something is "popping off."

| Field | Value |
|-------|-------|
| Source ID | `wikipedia_pageviews` |
| Cost | Free |
| Freshness | 1-2 hours |
| Auth | None (set User-Agent header with contact info) |
| Rate Limits | 200 req/sec |
| Signal Type | Mid-to-late (mainstream awareness confirmation) |

### API Documentation

| Resource | URL |
|----------|-----|
| Pageviews API reference | https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html |
| Getting started guide | https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/getting-started.html |
| Example queries | https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/examples/page-metrics.html |
| Pageviews analysis tool (web) | https://pageviews.wmcloud.org/ |

### Endpoint

```
GET https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/
    {project}/{access}/{agent}/{article}/{granularity}/{start}/{end}
```

**Example**: Daily human pageviews for "OpenAI" on English Wikipedia:
```
https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/
    en.wikipedia/all-access/user/OpenAI/daily/20260301/20260329
```

**Response**:
```json
{
  "items": [
    {
      "project": "en.wikipedia",
      "article": "OpenAI",
      "granularity": "daily",
      "timestamp": "2026032900",
      "access": "all-access",
      "agent": "user",
      "views": 45231
    }
  ]
}
```

### Module Dependencies (`wikipedia_pageviews/requirements.txt`)

```
requests>=2.32.0
```

### Implementation Plan

1. **Maintain a watchlist**: Map app names / trending keywords to Wikipedia article titles
2. **Daily poll**: Fetch pageviews for each article, compare to 7-day average
3. **Spike detection**: 3x+ daily average = signal, 10x+ = mainstream breakout
4. **Bot filtering**: Use `agent=user` to exclude automated traffic
5. **Coverage gap**: Not all apps have Wikipedia pages. This module is a confirmation signal, not a discovery signal.

---

## Module 8: YouTube Data API (PRIORITY 8)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `youtube` |
| Cost | Free (10K units/day = ~100 searches) |
| Freshness | Real-time |
| Auth | API key (Google Cloud project with YouTube Data API v3 enabled) |
| Rate Limits | 10,000 units/day; search = 100 units; video details = 1 unit |
| Signal Type | Mid (review/tutorial video velocity = growing interest) |

### API Documentation

| Resource | URL |
|----------|-----|
| YouTube Data API v3 | https://developers.google.com/youtube/v3 |
| API reference | https://developers.google.com/youtube/v3/docs |
| Getting started | https://developers.google.com/youtube/v3/getting-started |
| Quota calculator | https://developers.google.com/youtube/v3/determine_quota_cost |

### Module Dependencies (`youtube/requirements.txt`)

```
google-api-python-client>=2.100.0
```

### Implementation Plan

1. **Search for app reviews**: `q="{app_name} review" OR "{app_name} app"`, filter by upload date
2. **Track video velocity**: New review videos appearing for an app = growing interest
3. **View count tracking**: Sudden view spikes on app-related videos
4. **Budget**: 100 searches/day on free tier. Use channel RSS feeds (free, no quota) for known app review channels.

---

## Module 9: App Store Native Signals (PRIORITY 9)

### Overview

These are the free, no-auth signals directly from Apple's ecosystem.

| Field | Value |
|-------|-------|
| Source ID | `app_store_native` |
| Cost | Free |
| Freshness | Hours |
| Auth | None |
| Rate Limits | Undocumented (reasonable use) |
| Signal Type | Direct (these ARE App Store signals, not proxies) |

### Data Sources

| Source | URL | What It Provides |
|--------|-----|------------------|
| iTunes RSS Top Charts (JSON, v2) | `https://rss.applemarketingtools.com/api/v2/{country}/apps/top-free/{limit}/apps.json` | Current top free/paid/grossing apps per country (up to 200) |
| iTunes RSS Top Charts (legacy XML) | `https://itunes.apple.com/{country}/rss/topfreeapplications/limit={limit}/json` | Legacy format, still works |
| App Store Review RSS (JSON) | `https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json` | 50 reviews per page, 10 pages (500 most recent) |
| Apple RSS feed generator | https://rss.marketingtools.apple.com/ | Web tool to build custom RSS feeds |
| iTunes Search API | `https://itunes.apple.com/search?term={keyword}&country={cc}&entity=software` | Already used by RespectASO |

### Module Dependencies (`app_store_native/requirements.txt`)

```
requests>=2.32.0
```

### Implementation Plan

1. **Top Charts monitoring**: Poll top-free/top-paid/top-grossing hourly per country. Detect new entrants (apps appearing in top 200 for the first time).
2. **Review velocity tracking**: For tracked competitor apps, poll review RSS daily. Spike in review volume = download spike.
3. **Chart position delta**: Track position changes day-over-day. Rapid climbs = trending.
4. **New entrant extraction**: When a new app appears in top charts, extract its name and keywords for cross-referencing with other signal sources.

---

## Module 10: TikTok (PRIORITY 10)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `tiktok` |
| Cost | Free (Research API, if approved) or paid (Pentos, Exolyt) |
| Freshness | 1-3 days (Research API); near real-time (unofficial) |
| Auth | Research API application required |
| Rate Limits | Varies by approval |
| Signal Type | Early (massive trend driver for consumer apps) |

### Access Methods

| Method | Cost | Reliability |
|--------|------|-------------|
| TikTok Research API | Free (application required, weeks to approve) | High (when approved) |
| `TikTokApi` (unofficial Python library) | Free | **Fragile** — breaks frequently |
| Pentos (third-party) | Paid | Reliable |
| Exolyt (third-party) | Paid | Reliable |

### Module Dependencies (`tiktok/requirements.txt`)

```
requests>=2.32.0
# TikTokApi>=6.0.0  # optional: unofficial, fragile
```

### Implementation Plan

1. **If Research API approved**: Track hashtag volumes (#app, #musthaveapps, #techtoktips) and keyword mentions
2. **If not approved**: Monitor TikTok trends indirectly via Google Trends (TikTok trends spill into Google search within hours)
3. **Fallback**: Use Pentos/Exolyt for specific app name monitoring if budget allows

---

## Module 11: Bluesky (PRIORITY 11)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `bluesky` |
| Cost | Free |
| Freshness | Real-time |
| Auth | Account + app password |
| Rate Limits | 3,000 calls per IP per 5 minutes |
| Signal Type | Early (tech/media professionals) |

### API Documentation

| Resource | URL |
|----------|-----|
| Bluesky API docs | https://docs.bsky.app/docs/get-started |
| AT Protocol spec | https://atproto.com/ |
| AT Protocol SDKs | https://atproto.com/sdks |
| Rate limits | https://docs.bsky.app/docs/advanced-guides/rate-limits |
| atproto Python library | https://pypi.org/project/atproto/ |
| atproto docs | https://atproto.blue/ |
| atproto GitHub | https://github.com/MarshalX/atproto |

### Module Dependencies (`bluesky/requirements.txt`)

```
atproto>=0.0.50
```

---

## Module 12: Mastodon (PRIORITY 12)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `mastodon` |
| Cost | Free |
| Freshness | Real-time |
| Auth | OAuth 2.0 (register app on instance) |
| Rate Limits | 300 req/5 min per instance |
| Signal Type | Niche early (tech/FOSS/privacy community) |

### API Documentation

| Resource | URL |
|----------|-----|
| Mastodon API docs | https://docs.joinmastodon.org/api/ |
| Getting started | https://docs.joinmastodon.org/client/intro/ |
| Rate limits | https://docs.joinmastodon.org/api/rate-limits/ |
| Mastodon.py PyPI | https://pypi.org/project/Mastodon.py/ |
| Mastodon.py docs | https://mastodonpy.readthedocs.io/en/stable/ |
| Mastodon.py GitHub | https://github.com/halcy/Mastodon.py |

### Key Endpoints

```
GET /api/v1/trends/tags       — trending hashtags on this instance
GET /api/v1/trends/statuses   — trending posts
GET /api/v1/trends/links      — trending external links
```

### Module Dependencies (`mastodon/requirements.txt`)

```
Mastodon.py>=2.1.4
```

---

## Module 13: GitHub Trending (PRIORITY 13)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `github_trending` |
| Cost | Free |
| Freshness | Real-time (repo data); daily (trending page) |
| Auth | Personal access token recommended (5K req/hr vs 60 unauthenticated) |
| Rate Limits | 5,000 req/hr (authenticated) |
| Signal Type | Early for developer tools |

### API Documentation

| Resource | URL |
|----------|-----|
| GitHub REST API | https://docs.github.com/en/rest |
| GitHub GraphQL API | https://docs.github.com/en/graphql |
| Search repositories | https://docs.github.com/en/rest/search/search#search-repositories |

### Module Dependencies (`github_trending/requirements.txt`)

```
PyGithub>=2.1.0
```

### Implementation Plan

1. **Star velocity**: Search repos sorted by stars, filter by creation date. Repos gaining 100+ stars/day = trending.
2. **Topic filter**: Search by topics like "ios", "swift", "mobile", "app"
3. **Scrape trending page**: `https://github.com/trending?since=daily` as fallback

---

## Module 14: Steam Trending (PRIORITY 14)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `steam` |
| Cost | Free |
| Freshness | Real-time |
| Auth | API key (free at steamcommunity.com/dev/apikey) |
| Rate Limits | 100,000 calls/day |
| Signal Type | Gaming crossover |

### API Documentation

| Resource | URL |
|----------|-----|
| Steam Web API overview | https://partner.steamgames.com/doc/webapi_overview |
| Steam Web API reference | https://partner.steamgames.com/doc/webapi |
| Community developer docs | https://steamcommunity.com/dev |
| Unofficial API reference | https://steamapi.xpaw.me/ |

### Module Dependencies (`steam/requirements.txt`)

```
requests>=2.32.0
```

---

## Module 15: Podcast Index (PRIORITY 15)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `podcast_index` |
| Cost | Free |
| Freshness | Real-time |
| Auth | API key + secret (free at api.podcastindex.org) |
| Rate Limits | Generous (undocumented) |
| Signal Type | Mid (podcast features → download spikes) |

### API Documentation

| Resource | URL |
|----------|-----|
| Podcast Index API docs (OpenAPI) | https://podcastindex-org.github.io/docs-api/ |
| Developer portal | https://api.podcastindex.org/ |
| GitHub | https://github.com/Podcastindex-org/docs-api |
| Python library | https://pypi.org/project/python-podcastindex/ |

### Module Dependencies (`podcast_index/requirements.txt`)

```
python-podcastindex>=2.0.0
```

---

## Module 16: News APIs (PRIORITY 16)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `newsapi` |
| Cost | Free (100 req/day, 24h delayed) or $449/mo (real-time) |
| Freshness | Free: 24h delayed. Paid: real-time |
| Auth | API key (free signup at newsapi.org) |
| Rate Limits | Free: 100 req/day. Business: 250K req/mo |
| Signal Type | Mid (media coverage → search interest → downloads) |

**Important**: Bing News Search API was **RETIRED August 2025**. Its replacement
("Grounding with Bing Search") costs $35/1K transactions and requires Azure AI
Foundry SDK — no longer a standalone REST API. **Not recommended.**

GDELT (Module 6) is the recommended free alternative for news monitoring.

### API Documentation

| Resource | URL |
|----------|-----|
| NewsAPI.org docs | https://newsapi.org/docs |
| NewsAPI.org pricing | https://newsapi.org/pricing |
| Bing Search retirement notice | https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement |

### Module Dependencies (`newsapi/requirements.txt`)

```
requests>=2.32.0
```

### Pricing Comparison

| Service | Free Tier | Paid Tier | Notes |
|---------|-----------|-----------|-------|
| **GDELT** (Module 6) | Unlimited | N/A | Best free option. 15-min updates. |
| **NewsAPI.org** | 100 req/day, 24h delay, localhost only | $449/mo | Cannot deploy free tier to production |
| **Bing News** | **RETIRED** | $35/1K via Azure AI | Not standalone REST API anymore |

---

## Module 17: Paid ASO Providers (PRIORITY 17)

### Overview

| Field | Value |
|-------|-------|
| Source ID | `paid_aso` |
| Cost | $9–$5,000+/mo |
| Freshness | Hours to real-time |
| Auth | Per-provider |
| Signal Type | Direct (actual App Store intelligence) |

### Providers

| Provider | Starting Cost | API | Key Data |
|----------|---------------|-----|----------|
| AppFigures | ~$9/mo | REST | Keyword rankings, reviews, revenue estimates |
| AppFollow | ~$111/mo | REST | Reviews, ratings, keywords, ASO data |
| 42matters | ~$150/mo | REST | App metadata, SDK intelligence |
| Sensor Tower | ~$5K+/yr | REST | Downloads, revenue, keywords, ad intelligence |
| data.ai | Enterprise | REST | Gold standard but prohibitively expensive |

### Implementation Plan

This module is a wrapper/adapter that can integrate any paid provider's API. Start
with AppFigures ($9/mo) for keyword ranking data to supplement the free signals.

---

## Signal Correlation & Integration

### How Signals Flow into RespectASO

```
Signal Sources (Modules 1-17)
    ↓ write to
TrendSignal table (shared SQLite)
    ↓ correlate
Correlation Engine (find keywords in 2+ sources)
    ↓ trigger
RespectASO keyword search (existing PopularityEstimator + DifficultyCalculator)
    ↓ store
SearchResult table (existing)
    ↓ display
Dashboard with trend origin data
```

### Correlation Metrics

When evaluating whether a detected trend will translate to App Store searches,
weight signals by their predictive strength:

| Signal Type | Predictive Strength | Typical Lead Time |
|-------------|--------------------|--------------------|
| Google Trends spike | Very High | 0-24 hours (search → App Store search) |
| X/Twitter mention surge | High | 6-48 hours |
| Reddit post velocity | High | 12-72 hours |
| Product Hunt launch | Very High (for productivity/tools) | 24-72 hours |
| Hacker News front page | High (for dev tools) | 12-48 hours |
| GDELT news article spike | Medium-High | 24-72 hours |
| YouTube review videos | Medium-High | 24-96 hours |
| TikTok viral content | Very High (consumer apps) | 6-24 hours |
| Wikipedia pageview spike | Medium (confirmation) | 0-24 hours (lagging) |
| App Store chart movement | Direct signal | 0 hours (it's already happening) |
| Podcast mentions | Medium | 24-96 hours |
| GitHub star velocity | Medium (dev tools only) | 48-168 hours |

### Multi-Source Correlation Rules

```
CONFIDENCE LEVELS:

"Emerging Trend" (high confidence):
  - Keyword appears in 3+ sources within 48 hours
  - OR: Google Trends spike + any social source (Reddit/X/HN)
  - Action: Auto-trigger RespectASO keyword search + add to auto-refresh

"Possible Trend" (medium confidence):
  - Keyword appears in 2 sources within 48 hours
  - OR: Single-source spike > 10x baseline
  - Action: Add to monitoring queue, search in 24 hours if sustained

"Signal" (low confidence):
  - Keyword appears in 1 source with 3x+ baseline spike
  - Action: Log, monitor, no auto-action

"Mainstream" (confirmation):
  - Wikipedia pageview spike + App Store chart appearance
  - Action: The trend is already here. Focus on difficulty analysis.
```

### First-Detection Tracking

For every keyword, track when it was first detected and its propagation:

```json
{
    "keyword": "openclaw",
    "first_seen_at": "2026-03-29T14:30:00Z",
    "first_source": "reddit",
    "propagation": [
        {"source": "reddit",          "first_seen": "2026-03-29T14:30:00Z", "peak_volume": 150},
        {"source": "hacker_news",     "first_seen": "2026-03-29T16:00:00Z", "peak_volume": 85},
        {"source": "google_trends",   "first_seen": "2026-03-29T22:00:00Z", "peak_volume": 78},
        {"source": "x_twitter",       "first_seen": "2026-03-30T02:00:00Z", "peak_volume": 3200},
        {"source": "app_store_native","first_seen": "2026-03-30T08:00:00Z", "peak_volume": null},
        {"source": "wikipedia",       "first_seen": "2026-03-30T12:00:00Z", "peak_volume": 45000}
    ],
    "time_to_app_store": "17.5 hours",
    "confidence": "emerging_trend",
    "sources_count": 6
}
```

This data reveals the **typical propagation pattern** for trends: Reddit/social
→ HN/tech → Google search → X/mainstream social → App Store charts → Wikipedia.
Over time, this builds a model of how quickly trends propagate in specific
categories, improving prediction accuracy.

---

## Implementation Phases

### Phase 1: Core Free Stack (Week 1-2)

Implement and test the four highest-value free sources:

1. **Google Trends** — RSS feed parsing + pytrends-modern for interest-over-time
2. **Reddit** — PRAW subreddit monitoring for r/apps, r/iosapps, r/apple
3. **Hacker News** — Algolia API keyword search and front page monitoring
4. **GDELT** — News article volume tracking

Deliverables: TrendSignal model, 4 working collectors, basic correlation query.

### Phase 2: Social + Launch Signals (Week 3-4)

5. **Product Hunt** — Daily top launches monitoring
6. **App Store Native** — Top charts monitoring + review velocity
7. **Wikipedia Pageviews** — Watchlist-based pageview tracking

### Phase 3: Paid Signal Testing (Week 5-6)

8. **X/Twitter** — Pay-per-use with $50/month budget, counts endpoint first
9. **YouTube** — Free tier (100 searches/day) for review video tracking

### Phase 4: Extended Sources (Week 7-8)

10. **Bluesky** — AT Protocol post search
11. **Mastodon** — Trending tags/links on major instances
12. **GitHub Trending** — Star velocity for developer tools
13. **Podcast Index** — Episode search for app mentions

### Phase 5: Niche + Premium (As Needed)

14. **TikTok** — If Research API approved
15. **Steam** — If gaming crossover is relevant
16. **NewsAPI** — If GDELT coverage is insufficient
17. **Paid ASO** — Start with AppFigures if budget allows

---

## Sources

- [X API Official Pricing](https://docs.x.com/x-api/getting-started/pricing)
- [X API Pay-Per-Use Announcement](https://devcommunity.x.com/t/announcing-the-launch-of-x-api-pay-per-use-pricing/256476)
- [X API Pay-Per-Use Pilot](https://devcommunity.x.com/t/announcing-the-x-api-pay-per-use-pricing-pilot/250253)
- [X API Cost Breakdown (GetXAPI)](https://www.getxapi.com/blogs/twitter-api-cost)
- [Google Trends API Alpha](https://developers.google.com/search/apis/trends)
- [Google Trends API Announcement](https://developers.google.com/search/blog/2025/07/trends-api)
- [pytrends-modern GitHub](https://github.com/yiromo/pytrends-modern)
- [trendspyg GitHub](https://github.com/flack0x/trendspyg)
- [SerpAPI Google Trends](https://serpapi.com/google-trends-api)
- [Reddit Data API Wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki)
- [PRAW Documentation](https://praw.readthedocs.io/en/stable/)
- [Product Hunt API](https://api.producthunt.com/v2/docs)
- [HN Algolia API](https://hn.algolia.com/api)
- [Wikipedia Pageviews API](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html)
- [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [YouTube Data API v3](https://developers.google.com/youtube/v3)
- [Apple RSS Feed Generator](https://rss.marketingtools.apple.com/)
- [Bluesky API Docs](https://docs.bsky.app/docs/get-started)
- [AT Protocol](https://atproto.com/)
- [Mastodon API](https://docs.joinmastodon.org/api/)
- [Steam Web API](https://partner.steamgames.com/doc/webapi_overview)
- [Podcast Index API](https://podcastindex-org.github.io/docs-api/)
- [NewsAPI.org](https://newsapi.org/docs)
- [Bing Search API Retirement](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement)
