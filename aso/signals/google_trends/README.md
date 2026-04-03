# Google Trends Signal Collector

Fetches trending search data from Google Trends and stores it in the `TrendSignal` table. Three backends are available — pick the one that fits your budget and reliability needs.

## Quick Start (RSS — free, zero setup)

```bash
python manage.py collect_trends google_trends --backend rss --country us
```

This fetches the top ~20 trending topics for the US right now. No API key, no extra dependencies, works immediately. This is the recommended starting point.

---

## Backends Comparison

| Backend | Cost | Auth | Extra Deps | What It Does |
|---------|------|------|------------|--------------|
| **rss** | Free | None | None | Top ~20 daily trending topics per country |
| **pytrends** | Free | None | `pytrends-modern` | Interest-over-time + related rising queries for specific keywords |
| **serpapi** | $25+/mo | API key | `serpapi` | Same as pytrends but via SerpAPI (no scraping breakage risk) |

### When to use which

- **rss**: Discovery mode — "what's trending right now that might become an App Store search?"
- **pytrends**: Research mode — "is 'pilates' trending up or down this week?"
- **serpapi**: Production mode — same data as pytrends but won't break when Google changes their HTML

---

## Backend 1: RSS (recommended start)

Zero configuration. Uses Google's public RSS feed at `https://trends.google.com/trending/rss?geo=US`.

```bash
# US trending
python manage.py collect_trends google_trends --backend rss --country us

# Multiple countries (run separately)
python manage.py collect_trends google_trends --backend rss --country gb
python manage.py collect_trends google_trends --backend rss --country de
python manage.py collect_trends google_trends --backend rss --country jp
```

**What you get**: keyword, approximate traffic (e.g. "200K+", "1M+"), related news headlines.

**Limitations**: Only returns what's trending today. Cannot query specific keywords. No historical data.

---

## Backend 2: pytrends-modern (free, specific keywords)

### Install

```bash
pip install pytrends-modern
```

### Usage

```bash
# Interest-over-time for specific keywords
python manage.py collect_trends google_trends --backend pytrends \
  --keywords "pilates,yoga app,meditation,fitness tracker" \
  --country us

# Without keywords, falls back to RSS trending
python manage.py collect_trends google_trends --backend pytrends --country us
```

**What you get**: Google's 0-100 interest score for each keyword over the last 7 days, plus rising related queries (early signals for emerging keywords).

**Rate limits**: Google rate-limits aggressively. The collector adds 12-second delays between batches. Stick to 5-10 keywords per run. If you get 429 errors, wait a few minutes and retry.

### CLI (standalone, outside Django)

pytrends-modern includes its own CLI for quick checks:

```bash
# Quick interest check
pytrends-modern interest --keywords "pilates,yoga" --timeframe "today 12-m" --geo US

# RSS trending (same data as our rss backend)
pytrends-modern rss --geo US --format json

# Trending searches
pytrends-modern trending --geo US
```

---

## Backend 3: SerpAPI (paid, most reliable)

### Step 1: Get an API key

1. Go to [serpapi.com](https://serpapi.com) and create an account
2. Verify your email
3. Go to **Dashboard > API Key** — copy your key
4. Free tier: **250 searches/month** (enough for testing)

### Step 2: Install

```bash
pip install serpapi
```

### Step 3: Set your API key

```bash
# Option A: environment variable (recommended)
export SERPAPI_API_KEY="your_key_here"

# Option B: pass directly
python manage.py collect_trends google_trends --backend serpapi --api-key "your_key_here" ...
```

### Step 4: Usage

```bash
# Trending searches (costs 1 search)
python manage.py collect_trends google_trends --backend serpapi --country us

# Interest for specific keywords (costs 1 search per 5 keywords + 1 per keyword for related queries)
python manage.py collect_trends google_trends --backend serpapi \
  --keywords "pilates,yoga app" --country us
```

### SerpAPI Pricing

| Plan | Price/month | Searches/month |
|------|-------------|----------------|
| Free | $0 | 250 |
| Starter | $25 | 1,000 |
| Developer | $75 | 5,000 |
| Production | $150 | 15,000 |

Cached searches (same query within 1 hour) are free and don't count toward quota.

---

## Official Google Trends API (Alpha)

Google launched an official Trends API in alpha (July 2025). As of April 2026, it's still alpha-only with gated access. If you get approved:

### How to get access

1. Go to [developers.google.com/search/apis/trends](https://developers.google.com/search/apis/trends)
2. Submit the application form with your use case
3. If approved, Google whitelists your Google Cloud project

### How to set up (if approved)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select existing)
3. Navigate to **APIs & Services > Library**
4. Search for "Google Trends API" (only visible if your project is whitelisted)
5. Click **Enable**
6. Go to **APIs & Services > Credentials**
7. Click **Create Credentials > OAuth 2.0 Client ID**
8. Select **Desktop app** as the application type
9. Download `client.json`
10. First request will open a browser for OAuth consent, generating `token.json`

**Auth**: OAuth 2.0 (not API key). Scope: `https://www.googleapis.com/auth/trends.readonly`

**Endpoint**: `https://searchtrends.googleapis.com/v1alpha/`

**Quota**: ~10,000 data points/day. A 5-year daily query = 1,825 points, so ~5 keywords/day at daily resolution.

**No Python SDK yet** — you'd use `google-auth-oauthlib` + raw HTTP requests.

We haven't built a backend for this yet because the alpha quota is too low for practical use and access is gated. Once it goes GA, it'll likely become the primary backend.

---

## Data Flow

```
collect_trends command
  └── GoogleTrendsCollector(backend="rss|pytrends|serpapi")
        ├── .collect(keywords, country)
        │     └── returns list of dicts: keyword, raw_volume, normalized_score, metadata
        └── .save_signals(rows)
              └── upserts into TrendSignal table (keyed on source+keyword+country+date)
                    └── first_seen_at auto-populated from earliest existing record
```

## Supported Countries

RSS and SerpAPI support these country codes:
`us`, `gb`, `ca`, `au`, `de`, `fr`, `jp`, `kr`, `br`, `in`, `mx`, `es`, `it`, `nl`, `se`, `no`, `dk`, `fi`, `pl`, `ru`

Pass any ISO-3166-1 alpha-2 code — unmapped codes are sent uppercase to Google directly.

---

## Querying Collected Data

```python
from aso.models import TrendSignal

# All signals from today
TrendSignal.objects.filter(date_stamp=date.today())

# Cross-source correlation: keywords appearing in 2+ sources within 48h
from django.db.models import Count, Min
TrendSignal.objects.filter(
    collected_at__gte=now - timedelta(hours=48)
).values("keyword").annotate(
    source_count=Count("source", distinct=True),
    earliest=Min("first_seen_at"),
).filter(source_count__gte=2).order_by("-source_count")

# Rising keywords from Google Trends
TrendSignal.objects.filter(
    source="google_trends",
    metadata__method="pytrends_related_rising",
).order_by("-raw_volume")
```
