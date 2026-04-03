# iOS Keyword Volume & Trend Intelligence

A comprehensive reference covering how RespectASO derives keyword popularity,
difficulty, and download estimates from public data — and a catalog of external
trend data sources that can detect emerging App Store search demand before
traditional keyword tools.

---

## Table of Contents

1. [The Fundamental Problem](#1-the-fundamental-problem)
2. [Data Source: iTunes Search API](#2-data-source-itunes-search-api)
3. [Popularity Estimator — 6 Signals](#3-popularity-estimator--6-signals)
4. [Difficulty Calculator — 7 Factors](#4-difficulty-calculator--7-factors)
5. [Download Estimator](#5-download-estimator)
6. [Title Evidence & Brand Detection](#6-title-evidence--brand-detection)
7. [Post-Processing: Apple Backfill Correction](#7-post-processing-apple-backfill-correction)
8. [Ranking Tier Analysis](#8-ranking-tier-analysis)
9. [Opportunity Signals](#9-opportunity-signals)
10. [Known Limitations](#10-known-limitations)
11. [External Trend Data Sources](#11-external-trend-data-sources)
12. [Recommended Integration Stack](#12-recommended-integration-stack)

---

## 1. The Fundamental Problem

Apple does not publish keyword search volume data through any public API.

The **iTunes Search API** (`itunes.apple.com/search`) returns app metadata only:
names, ratings, review counts, release dates, genres, icons, prices. There is no
field for search volume, impressions, or keyword popularity.

The only official source for keyword popularity is the **Apple Search Ads API**,
which:
- Requires an Apple Search Ads account (gated access)
- Provides a relative 5–100 popularity score (not absolute volume)
- Was significantly degraded in September 2025 when Apple rebuilt the scoring
  algorithm, causing a 77% drop in tracked keywords (from ~166K to ~39K in the
  US alone)
- Shifted toward monthly aggregated rank reports instead of daily signals

Apple's v4 keyword recommendations endpoint was deprecated in 2025, and v5 never
included it.

**RespectASO's approach**: reverse-infer popularity from the competitive
landscape. The core insight (`aso/services.py:234–235`):

> "Keywords with high search volume attract strong apps. If heavyweight players
> rank for a keyword, users are searching for it."

This is proxy-based estimation — not ground truth. Every score in this system is
a best-effort inference from publicly available signals.

---

## 2. Data Source: iTunes Search API

**Source file**: `aso/services.py:437–549` (`ITunesSearchService`)

### Endpoints

| Endpoint | URL | Purpose |
|----------|-----|---------|
| Search | `GET https://itunes.apple.com/search` | Find apps matching a keyword |
| Lookup | `GET https://itunes.apple.com/lookup` | Get metadata for a specific app by ID |

### Search Parameters

```
term     = {keyword}        # The search query
country  = {2-letter code}  # e.g. "us", "gb", "de"
entity   = software         # iOS apps only
limit    = {1–200}          # Default 10 in code; 200 for rank finding
```

No authentication. No API key. Rate limit ~20 requests/minute per IP.

### Parsed Fields (`_parse_app`, line 530–549)

Every algorithm in this system operates on these fields extracted from the API:

| Field | Type | Used By |
|-------|------|---------|
| `trackId` | int | Rank finding, app identification |
| `trackName` | string | Title matching (popularity signals 3/6, difficulty factor 7) |
| `userRatingCount` | int | Leader strength, market depth, dominant players, rating volume, review velocity, weak competitor detection |
| `averageUserRating` | float (0–5) | Rating quality factor |
| `releaseDate` | ISO date | Market age, review velocity, fresh entrant detection |
| `currentVersionReleaseDate` | ISO date | Stored but not currently scored |
| `primaryGenreName` | string | Genre diversity, finance context detection |
| `sellerName` | string | Publisher diversity, brand keyword detection |
| `formattedPrice` | string | Display only |
| `description` | string (truncated to 200 chars) | Display only |
| `bundleId` | string | App identification |
| `artworkUrl100` | URL | Display only |
| `trackViewUrl` | URL | Display only |

### Fields Available but NOT Extracted

The iTunes API returns additional fields that the current code does not use:

- `averageUserRatingForCurrentVersion` — per-version rating
- `userRatingCountForCurrentVersion` — per-version review count
- `fileSizeBytes` — app binary size
- `releaseNotes` — latest update description
- `screenshotUrls` / `ipadScreenshotUrls` — screenshot URLs
- `languageCodesISO2A` — supported languages
- `supportedDevices` — device compatibility list
- `contentAdvisoryRating` — age rating
- `genreIds` / `genres` — full genre taxonomy
- `artistId` — developer ID
- `price` / `currency` — numeric price and currency code
- `artworkUrl512` / `artworkUrl60` — additional icon sizes
- `isGameCenterEnabled` — Game Center integration flag

---

## 3. Popularity Estimator — 6 Signals

**Source file**: `aso/services.py:226–429` (`PopularityEstimator`)

**Input**: List of competitor app dicts from iTunes Search + keyword string
**Output**: Integer score 5–100, or `None` if no competitors
**Scale**: Matches the legacy Apple Search Ads 5–100 range

### Signal 1: Result Count (0–25 points)

**Line 268–270** | Data: `len(competitors)`

More results returned by iTunes = broader/more popular topic.

```
result_score = min(25, n * 2.5)
```

| Results (n) | Points |
|-------------|--------|
| 1 | 2.5 |
| 5 | 12.5 |
| 10+ | 25.0 (max) |

### Signal 2: Leader Strength (0–30 points)

**Lines 272–305** | Data: `userRatingCount` of top-half competitors

Only considers apps in the **top half** of results — tail apps are often backfill
from broader terms (e.g. Pokemon GO appearing at #24 for unrelated keywords).

Uses smooth logarithmic interpolation between calibration bands:

```
max_reviews = max(c["userRatingCount"] for c in top_half_competitors)
```

| Max Reviews (top half) | Points |
|------------------------|--------|
| 0 | 0 |
| 10 | 1 |
| 100 | 5 |
| 1,000 | 10 |
| 10,000 | 17 |
| 100,000 | 24 |
| 1,000,000+ | 30 |

**Interpolation formula** (between adjacent bands):

```python
ratio = log(max_reviews / prev_threshold) / log(threshold / prev_threshold)
score = prev_score + ratio * (score - prev_score)
```

**Logic**: If the #1 app for this keyword has 500K+ reviews, the keyword must be
attracting serious players and therefore has significant search volume.

### Signal 3: Title Match Density (0–20 points)

**Lines 307–325** | Data: `trackName` of each competitor

Counts how many competitors have the keyword in their title (exact phrase or all
words in any order). Uses `_keyword_title_evidence()` for matching.

```python
match_ratio = title_matches / n
title_score = min(20, match_ratio * 40)
```

| Match Ratio | Points |
|-------------|--------|
| 0% | 0 |
| 25% | 10 |
| 50%+ | 20 (max) |

**Logic**: Developers optimize their titles for keywords with proven demand. If
80% of competitors have the keyword in their title, it's real demand evidence.

### Signal 4: Market Depth (0–10 points)

**Lines 327–364** | Data: MEDIAN of `userRatingCount` across all competitors

The median (not mean) prevents a single mega-app from skewing the assessment.

Smooth logarithmic interpolation between calibration bands:

| Median Reviews | Points |
|----------------|--------|
| 0 | 0 |
| 10 | 0.5 |
| 100 | 3 |
| 1,000 | 5 |
| 10,000 | 8 |
| 50,000+ | 10 |

**Logic**: If even the median-ranked competitor has substantial reviews, the
entire market is deep — indicating sustained search volume driving installs.

### Signal 5: Keyword Specificity Penalty (-28 to 0 points)

**Lines 366–390** | Data: word count of keyword string

Long-tail keywords inherently have lower search volume. "scanner" gets more
searches than "card value scanner for pokemon".

Smooth linear interpolation between calibration points:

| Word Count | Penalty |
|------------|---------|
| 1 | 0 |
| 2 | -3 |
| 3 | -8 |
| 4 | -15 |
| 5 | -22 |
| 6+ | -28 |

This is the strongest differentiator between head and long-tail terms.

### Signal 6: Exact Phrase Match Bonus (0–15 points)

**Lines 392–398** | Data: exact substring matches in `trackName`

```python
exact_ratio = exact_phrase_matches / n
exact_bonus = min(15, exact_ratio * 50)
```

| Exact Ratio | Points |
|-------------|--------|
| 0% | 0 |
| 10% | 5 |
| 20% | 10 |
| 30%+ | 15 (max) |

**Logic**: If competitors have the EXACT phrase in their titles, it's a known,
established search term that developers specifically target.

### Dampening Layers

#### Small Sample Dampening (lines 400–407)

Ratio-based signals (title_score, exact_bonus) are unreliable with few results.
1/1 = 100% is a math artifact, not real demand evidence.

```python
sample_dampening = min(1.0, n / 10)
title_score  *= sample_dampening
exact_bonus  *= sample_dampening
```

Linear ramp reaching full strength at n = 10.

#### Backfill-Aware Dampening (lines 409–419)

When few competitors have the keyword in their title, Apple is padding results
with unrelated apps. The evidence scores from `_keyword_title_evidence()` are
aggregated:

```python
relevance_ratio = relevance_sum / n
relevance = max(0.3, min(1.0, relevance_ratio * 2.6))
result_score *= relevance
leader_score *= relevance
depth_score  *= relevance
```

Clamps to [0.3, 1.0]. At 0 relevance, scores are reduced to 30% of face value.

### Final Score

```python
total = int(
    result_score
    + leader_score
    + title_score
    + depth_score
    + specificity_penalty
    + exact_bonus
)
return max(5, min(100, total))
```

**Theoretical range**: 5–100 (clamped)
**Maximum possible** (before clamping): 25 + 30 + 20 + 10 + 0 + 15 = **100**
**Minimum possible** (before clamping): 0 + 0 + 0 + 0 + (-28) + 0 = **-28** → clamped to **5**

---

## 4. Difficulty Calculator — 7 Factors

**Source file**: `aso/services.py:797–2069` (`DifficultyCalculator`)

**Input**: List of competitor app dicts from iTunes Search + keyword string
**Output**: Integer score 1–100, plus detailed breakdown dict
**All sub-scores normalized to 0–100 before weighting**

### Factor 1: Rating Volume (30% weight)

**Lines 874–884, 1855–1899** | Data: MEDIAN of `userRatingCount`

Log-scale mapping of the median review count across all competitors. Uses median
instead of mean to prevent outliers from skewing.

| Median Reviews | Sub-score (0–100) |
|----------------|-------------------|
| 0 | 0 |
| 50 | 5 |
| 200 | 15 |
| 500 | 30 |
| 2,000 | 50 |
| 5,000 | 65 |
| 10,000 | 78 |
| 25,000 | 88 |
| 100,000+ | 95–100 |

Interpolation: logarithmic between bands (same `log(x/prev) / log(next/prev)`
method used throughout).

### Factor 2: Review Velocity (10% weight)

**Lines 886–887, 1901–1969** | Data: `userRatingCount` and `releaseDate`

Median reviews-per-year across competitors. Distinguishes active, growing markets
from stagnant ones.

```python
age_years = max(0.5, (now - released).days / 365.25)
velocity = reviews / age_years
median_velocity = median(all velocities)
```

| Median Velocity (reviews/yr) | Sub-score (0–100) |
|------------------------------|-------------------|
| 0 | 0 |
| 10 | 5 |
| 50 | 15 |
| 200 | 30 |
| 1,000 | 50 |
| 5,000 | 70 |
| 20,000 | 85 |
| 50,000+ | 95–100 |

Minimum app age clamped to 0.5 years to prevent division-by-zero spikes for
brand-new apps.

### Factor 3: Dominant Players (20% weight)

**Lines 889–911** | Data: `userRatingCount` per competitor

Continuous log-scale dominance assessment. Each competitor contributes a dominance
signal on a 0–1 scale, with top-half competitors weighted 2x.

```python
log_ceiling = log10(10,000,000)  # = 7.0

for each competitor at position i:
    app_dominance = min(1.0, log10(max(reviews, 1)) / log_ceiling)
    weight = 2.0 if i < top_half_size else 1.0
    dominance_total += app_dominance * weight

dominant_players = min(100, (dominance_total / weight_sum) * 100)
```

**Per-app dominance values**:

| Reviews | Dominance (0–1) |
|---------|-----------------|
| 1 | 0.00 |
| 100 | 0.29 |
| 1,000 | 0.43 |
| 10,000 | 0.57 |
| 100,000 | 0.71 |
| 1,000,000 | 0.86 |
| 10,000,000 | 1.00 |

### Factor 4: Rating Quality (10% weight)

**Lines 913–932, 1971–2012** | Data: `averageUserRating` and `userRatingCount`

Log-weighted average of star ratings across competitors. The `log1p` weighting
prevents mega-apps from completely dominating while respecting review volume:

```python
weight = log1p(reviews)
# 1 review → 0.7, 10 → 2.4, 100 → 4.6, 1000 → 6.9, 10000 → 9.2

weighted_avg = sum(rating * log1p(reviews)) / sum(log1p(reviews))
```

| Weighted Avg Rating | Sub-score (0–100) |
|---------------------|-------------------|
| 0.0 | 0 |
| 3.0 | 20 |
| 3.5 | 35 |
| 4.0 | 50 |
| 4.3 | 70 |
| 4.5 | 85 |
| 5.0 | 100 |

Interpolation: linear between calibration points.

### Factor 5: Market Age (10% weight)

**Lines 934–935, 2014–2068** | Data: `releaseDate` of each competitor

Average age (in years) of all competitor apps.

| Average Age | Sub-score (0–100) |
|-------------|-------------------|
| < 0.5 yr | 0–10 |
| 0.5 yr | 10 |
| 1 yr | 20 |
| 2 yr | 35 |
| 3 yr | 50 |
| 5 yr | 70 |
| 8 yr | 85 |
| 10+ yr | 100 |

Interpolation: linear between calibration points.

### Factor 6: Publisher Diversity (10% weight)

**Lines 937–945** | Data: unique `sellerName` values

```python
unique_publishers = len(set(c["sellerName"] for c in competitors))
publisher_diversity = min(100, (unique_publishers / n) * 100)
```

A score of 100 means every competitor is from a different publisher (fragmented
market). Lower scores indicate one publisher dominates multiple positions.

### Factor 7: Title Relevance (10% weight)

**Lines 947–962** | Data: `trackName` keyword matching

```python
title_match_count = count of apps with exact_phrase OR all_words match
title_relevance = min(100, (title_match_count / n) * 100)
```

Measures whether competitors are actively optimizing for this keyword or if Apple
is showing generic backfill.

### Dampening (Same Two Layers as Popularity)

**Small sample dampening** (lines 964–978):

```python
sample_dampening = min(1.0, full_result_count / 10)
```

Applied to: publisher_diversity, title_relevance, dominant_players, rating_quality.

**Backfill-aware dampening** (lines 980–993):

```python
relevance = max(0.3, min(1.0, relevance_ratio * 2.6))
```

Applied to: publisher_diversity, rating_quality, market_age.

### Weighted Total Formula

```python
raw_total = int(
    rating_volume      * 0.30
    + review_velocity  * 0.10
    + dominant_players * 0.20
    + rating_quality   * 0.10
    + market_age       * 0.10
    + publisher_diversity * 0.10
    + title_relevance  * 0.10
)
total = max(1, min(100, raw_total))
```

### Difficulty Interpretation Bands

| Score | Label |
|-------|-------|
| 1–15 | Very Easy |
| 16–35 | Easy |
| 36–55 | Moderate |
| 56–75 | Hard |
| 76–90 | Very Hard |
| 91–100 | Extreme |

---

## 5. Download Estimator

**Source file**: `aso/services.py:557–789` (`DownloadEstimator`)

**Formula**:

```
Daily Downloads = Daily Searches × TTR(position) × CVR × Market Size
```

### Component 1: Popularity → Daily Searches

**Lines 585–731** | Piecewise-linear interpolation

Calibrated against industry ASO data and real download/rank observations. Apple's
popularity scale is roughly logarithmic — each point at the top represents a much
larger absolute search increment than at the bottom.

Anchor point: popularity 68, rank #8 → low single-digit downloads/day for
early-stage apps in competitive categories.

| Popularity Score | Est. Daily Searches (US) |
|------------------|--------------------------|
| 5 | 1 |
| 10 | 3 |
| 15 | 5 |
| 20 | 10 |
| 25 | 20 |
| 30 | 35 |
| 35 | 55 |
| 40 | 90 |
| 45 | 140 |
| 50 | 200 |
| 55 | 290 |
| 60 | 400 |
| 65 | 550 |
| 70 | 750 |
| 75 | 1,100 |
| 80 | 2,000 |
| 85 | 4,000 |
| 90 | 8,000 |
| 95 | 16,000 |
| 100 | 32,000 |

### Component 2: Position → Tap-Through Rate (TTR)

**Lines 609–646**

App Store search shows 2–3 full app cards per screen (icon, title, subtitle,
screenshots, GET button). Position #1 is always fully visible and dominates
attention.

**References cited in code**:
- Apple Search Ads average TTR ~7.5% for paid placements; organic #1 should be
  well above that
- Google web-search #1 CTR is 27–32% with plain text links; App Store's visual
  cards give #1 even more prominence
- ASO industry studies (Phiture, StoreMaven) report 25–50% engagement for the
  top organic result

Follows a power-law decay: steep drop #1–#5 (first screen), gradual tail for
scroll positions.

| Position | TTR (%) |
|----------|---------|
| 1 | 30.00% |
| 2 | 18.00% |
| 3 | 12.00% |
| 4 | 8.50% |
| 5 | 6.00% |
| 6 | 4.50% |
| 7 | 3.30% |
| 8 | 2.50% |
| 9 | 1.90% |
| 10 | 1.30% |
| 11 | 0.90% |
| 12 | 0.70% |
| 13 | 0.55% |
| 14 | 0.42% |
| 15 | 0.33% |
| 16 | 0.25% |
| 17 | 0.19% |
| 18 | 0.14% |
| 19 | 0.10% |
| 20 | 0.07% |

### Component 3: Conversion Rate (CVR)

**Lines 648–653**

```
CVR_LOW  = 0.05  (5%)   — Unknown indie app, weak listing, few ratings
CVR_HIGH = 0.20  (20%)  — Category leader, strong brand, 100K+ ratings
```

Downloads are always shown as a low–high range using these two bounds.

### Component 4: Market Size Multiplier

**Lines 660–712**

Scales search volumes relative to the US. The `_POP_TO_SEARCHES` table is
calibrated for the US App Store (~180M active iPhones). Smaller markets have
proportionally fewer searches for the same popularity score.

Derived from estimated active-iPhone installed base per country relative to US.

| Country | Multiplier | | Country | Multiplier |
|---------|------------|---|---------|------------|
| US | 1.00 | | TW | 0.08 |
| CN | 0.45 | | NL | 0.07 |
| JP | 0.35 | | SE | 0.06 |
| GB | 0.30 | | CH | 0.06 |
| DE | 0.25 | | PL | 0.05 |
| FR | 0.22 | | TR | 0.05 |
| KR | 0.20 | | TH | 0.05 |
| BR | 0.18 | | ID | 0.05 |
| IN | 0.15 | | BE | 0.04 |
| CA | 0.15 | | AT | 0.04 |
| AU | 0.12 | | NO | 0.04 |
| RU | 0.12 | | DK | 0.04 |
| IT | 0.12 | | SG | 0.04 |
| ES | 0.10 | | IL | 0.04 |
| MX | 0.10 | | AE/SA/PH/MY | 0.04 |

Tier 4 countries (ZA, IE, FI, PT, NZ, CL, AR, CO, NG, EG): **0.03**
Tier 5 countries (PK, KE, GH, TZ, UG): **0.02**
Default (unlisted countries): **0.03**

### Output Structure

```python
{
    "daily_searches": float,
    "positions": [
        {"pos": 1, "ttr": 30.0, "downloads_low": float, "downloads_high": float},
        ...  # positions 1–20
    ],
    "tiers": {
        "top_5":     {"low": float, "high": float},  # avg daily DLs for pos 1-5
        "top_6_10":  {"low": float, "high": float},  # avg daily DLs for pos 6-10
        "top_11_20": {"low": float, "high": float},  # avg daily DLs for pos 11-20
    }
}
```

---

## 6. Title Evidence & Brand Detection

### Title Evidence Scoring

**Source file**: `aso/services.py:82–148` (`_keyword_title_evidence`)

Determines how strongly a competitor's title matches the search keyword. Used by
both PopularityEstimator and DifficultyCalculator.

**Match hierarchy** (strongest → weakest):

| Match Type | Evidence Score | Description |
|------------|---------------|-------------|
| Exact phrase | 1.0 | Keyword appears as exact substring in title |
| All words (any order) | 0.85–1.0 | All keyword tokens present; proximity bonus up to 1.0 |
| Partial overlap | 0.0–0.5 | Some but not all tokens match; `overlap * 0.5` |
| No match | 0.0 | None of the keyword tokens found |

**Proximity bonus** for all-word matches (lines 110–119):

```python
span = max(positions) - min(positions) + 1
proximity = min(1.0, len(keyword_tokens) / span)
score = 0.85 + 0.15 * proximity
```

Words closer together in the title score higher — "card scanner" in "Card Scanner
Pro" scores higher than "Card Collector Document Scanner".

**Finance ambiguity guard** (lines 121–130):

Keywords with finance intent tokens ("option", "trading", "stock", "call", etc.)
are downgraded when the title doesn't have finance context. This prevents generic
apps (e.g., a "Call Recorder" app) from being counted as relevant for the keyword
"call option trading".

### Brand Keyword Detection

**Source file**: `aso/services.py:151–218` (`_is_brand_keyword`)

Detects when a keyword is a brand/company name (e.g., "spotify", "nasdaq") to
prevent incorrect difficulty adjustments.

**Signal A — Seller name match (required)**:
All keyword tokens must appear in the #1 app's `sellerName`.

**Signal B — Review disparity (required only for weak leaders)**:
When the leader has < 1,000 reviews, also requires that independent runners-up
(positions #2–5, excluding same-seller apps) have a median >= 10,000 reviews.
This confirms Apple is rank-boosting a brand companion app rather than the keyword
being genuinely weak.

For strong leaders (>= 1,000 reviews), seller-name match alone is sufficient.

---

## 7. Post-Processing: Apple Backfill Correction

**Source file**: `aso/services.py:1077–1172`

When Apple's search can't find enough apps matching a specific keyword, it
backfills with popular apps from broader terms. These three overrides correct
the inflated difficulty scores.

### Override 1: Small Result Set Cap (lines 1100–1116)

When Apple returns very few results, cap the difficulty score:

| Results (n) | Maximum Score |
|-------------|---------------|
| 1 | 10 |
| 2 | 20 |
| 3 | 31 |
| 4 | 40 |
| 5+ | No cap |

### Override 2: Weak Leader Cap (lines 1118–1148)

When the #1 app has < 1,000 reviews (and it's not a brand keyword), apply a
logarithmic cap:

```python
leader_cap = 15 + 35 * log10(leader_reviews + 1) / log10(1001)
```

| Leader Reviews | Cap |
|----------------|-----|
| 0 | 15 |
| 10 | 27 |
| 50 | 35 |
| 100 | 39 |
| 500 | 47 |
| 999 | 50 |

**Blending with title match ratio** (lines 1144–1147): When many competitors
target the keyword (high match_ratio), the cap is softened:

```python
if match_ratio > 0.2:
    total = leader_cap + (total - leader_cap) * match_ratio
else:
    total = leader_cap
```

### Override 3: Backfill Discount (lines 1150–1172)

When few competitors match the keyword in title AND the leader is weak:

```python
ratio_factor  = min(1.0, 0.6 + 2.0 * match_ratio)    # 0→0.6×, 0.2→1.0×
leader_factor = log10(leader_reviews + 1) / log10(1001)
discount      = ratio_factor + (1.0 - ratio_factor) * leader_factor
discount      = max(0.6, min(1.0, discount))
total         = max(1, int(total * discount))
```

Triggers when: `match_ratio < 0.2 AND leader_reviews < 1,000 AND NOT
brand_keyword`

---

## 8. Ranking Tier Analysis

**Source file**: `aso/services.py:1328–1542` (`_compute_ranking_tiers`)

Computes separate difficulty assessments for Top 5, Top 10, and Top 20 positions,
using the same `_compute_raw_difficulty()` algorithm on each tier's subset.

### Key design decisions:

1. **Full result count for dampening** (line 1385): Tier slices use the FULL
   result count for sample dampening, not the tier size — so a Top 5 slice from
   a 25-result keyword gets proper dampening.

2. **Overall context for post-processing** (lines 1395–1417): Tiers inherit the
   overall keyword's match_ratio and leader_reviews for weak-leader and backfill
   corrections, preventing inconsistencies.

3. **Floor enforcement** (lines 1487–1514): Every tier score must be >= the
   overall difficulty score. Top-5 is always at least as hard as competing at all.

4. **Monotonicity** (lines 1516–1540): Larger tiers can never be harder than
   smaller tiers. If Top 5 is "Hard", Top 10 and Top 20 must be "Hard" or
   easier.

### Per-Tier Data

For each tier (top_5, top_10, top_20):

| Field | Description |
|-------|-------------|
| `tier_score` | Difficulty 1–100 |
| `label` | Very Easy / Easy / Moderate / Hard / Very Hard / Extreme |
| `min_reviews` | Review count of the weakest app in tier |
| `weakest_app` | Name of that app |
| `median_reviews` | Median review count within tier |
| `weak_count` | Apps with < 1K reviews |
| `fresh_count` | Apps released in last 12 months |
| `title_keyword_count` | Apps with keyword in title |
| `total_apps` | Actual apps in tier (may be < tier size) |
| `highlights` | List of plain-English bullet strings |

---

## 9. Opportunity Signals

**Source file**: `aso/services.py:1736–1852` (`_find_opportunities`)

Four signals computed but not included in the difficulty score — they are
qualitative overlays for developer decision-making.

### Title Gap

When no or few competitors have the exact keyword in their title:
- **Strong**: 0 out of n apps → "Exact-match title optimization could give you
  an edge"
- **Moderate**: <= n/3 apps → "There's room for title optimization"

### Weak Competitors

Apps with < 1,000 reviews in the result set:
- Reports count, names the weakest, and labels positions as "displaceable"

### Active Market (Fresh Entrants)

Apps released in the last 12 months:
- Indicates the market is still attracting new entrants

### Cross-Genre

Results spanning 3+ genres:
- Signals the keyword isn't locked to one category — a well-positioned app in any
  genre could rank

---

## 10. Known Limitations

### Fundamental

1. **No ground truth**: All scores are proxy estimates. There is no public data
   to validate against actual Apple search volumes.
2. **Correlation ≠ causation**: Strong apps ranking for a keyword doesn't
   guarantee high search volume. Some keywords attract strong apps for strategic
   reasons (brand defense, category coverage).
3. **The pop-to-searches mapping is a calibration guess**: The table mapping
   popularity 50 → 200 searches/day has no public Apple data backing it. Paid
   ASO tools calibrate against actual Search Ads impression data; RespectASO
   cannot.
4. **Apple's search ranking != iTunes Search API order**: The order of results
   from the iTunes Search API may not match actual App Store search rankings on
   device.

### Algorithmic

5. **No historical signal**: Each search is a point-in-time snapshot. Trends are
   only tracked by re-searching the same keyword over time.
6. **No seasonality awareness**: "Christmas wallpaper" should score higher in
   December. The system has no temporal adjustment.
7. **No category normalization**: A "popular" keyword in Utilities means something
   different than in Games. Thresholds are universal.
8. **Single-language**: Title matching works for English; languages without spaces
   (Chinese, Japanese, Korean) may not tokenize correctly.

### Data Quality

9. **iTunes Search API quirks**: Apple sometimes returns inconsistent result
   counts for the same query. Rate limiting can cause silent failures.
10. **Backfill detection is heuristic**: The relevance dampening and
    post-processing overrides are tuned for common cases but can misclassify.
11. **Review counts are cumulative**: An app with 100K reviews accumulated over 10
    years is very different from one that got 100K in 6 months. Review velocity
    partially addresses this but uses total reviews / total age, not recent
    velocity.

---

## 11. External Trend Data Sources

The following sources can detect emerging search trends **before** they appear in
App Store keyword tools. Traditional keyword tools (Google Keyword Planner, Apple
Search Ads) lag by weeks; these sources range from real-time to hours behind.

### 11.1 Google Trends

**What it is**: Google's public tool showing relative search interest over time.
There is **no official API** — the website is the only official interface.

**Why it matters**: Google search interest is one of the strongest predictors of
App Store trends. When people Google an app or concept, App Store searches follow
within hours to days.

**Data types**:
- **Real-time trending searches**: Updated every few minutes. What is surging
  *right now*. Filterable by category (Sci/Tech, Entertainment, etc.).
- **Interest over time**: Historical relative interest (0–100 scale). Daily
  granularity delayed 24–72 hours. Weekly data delayed further.
- **Related queries**: Shows related rising/breakout queries for a topic.
- **Category 31** = "Mobile Apps & Add-Ons" — can filter to app-related searches.

**Access methods**:

| Method | Cost | Reliability | Notes |
|--------|------|-------------|-------|
| Official Google Trends API (alpha) | Free (application required) | **Best** — official, launched July 2025 | Apply at developers.google.com/search/apis/trends |
| `pytrends` (Python) | Free | **DEAD** — archived April 2025 | Do not use. Repository archived by owner. |
| `pytrends-modern` (Python) | Free | Active — latest release March 2026 | Fork/evolution of pytrends. RSS + Selenium. github.com/yiromo/pytrends-modern |
| `trendspyg` (Python) | Free | Active — latest release Jan 2026 | RSS-based (~0.2s, no browser needed). github.com/flack0x/trendspyg |
| SerpAPI | $25+/mo (1K searches) | **Reliable** — handles proxy rotation, CAPTCHA, endpoint changes | Best for production use. serpapi.com/google-trends-api |
| Google Trends RSS | Free | Stable | `trends.google.com/trending/rss?geo=US` — top daily trending topics with traffic counts. |

**Freshness**: Real-time trending = minutes. Interest over time = 1–3 days.

### 11.2 X (Twitter) API

**What it is**: X's official API for accessing tweet data, trending topics, and
search analytics.

**Why it matters**: New apps and concepts often trend on X hours to days before
they trend on search engines. Hashtag velocity and mention spikes are leading
indicators.

**Pricing (Pay-Per-Use, launched February 2026)**:

X killed the old subscription tiers (Basic $200/mo, Pro $5,000/mo) in January
2026 and moved to pay-per-use credits. No subscriptions — pay only for what
you use.

| Operation | Cost per Request |
|-----------|-----------------|
| Post read (fetch tweet) | $0.005 |
| Post create (write tweet) | $0.010 |
| User profile lookup | $0.010 |
| DM event read | $0.010 |
| DM interaction create | $0.015 |
| User interaction (follow, like, retweet) | $0.015 |

- Purchase credits upfront in the Developer Console
- 24-hour UTC deduplication: same resource fetched twice in a day = 1 charge
- Monthly cap: 2M post reads. Beyond that → Enterprise ($42K+/mo)
- Spending $200+/month earns 10-20% back as xAI API credits
- Legacy Free tier users get a one-time $10 voucher

**Key endpoints**:

| Endpoint | What It Does | Cost |
|----------|-------------|------|
| `GET /2/tweets/counts/recent` | Tweet volume for a query in 1min/1hr/1day buckets, last 7 days | Per-request credit |
| `GET /2/tweets/counts/all` | Full-archive tweet counts | Per-request credit |
| `GET /2/tweets/search/recent` | Last 7 days of matching tweets | $0.005/post read |
| `GET /2/tweets/search/all` | Full-archive search | $0.005/post read |
| `GET /2/tweets/search/stream` | Real-time filtered stream | $0.005/post read |

**Query operators** (work in search, counts, and stream):

```
#hashtag              — Track hashtag volume
"exact phrase"        — Track phrase mentions
@username             — Track account mentions
from:username         — Track tweets from account
url:"apps.apple.com"  — Track App Store links
(#aso OR "app store") -is:retweet lang:en  — Complex boolean queries
```

**Cost examples**:
- 10,000 post reads/month = **$50**
- 50,000 post reads/month = **$250**
- 100,000 post reads/month = **$500**

**Cheaper alternatives**:

| Service | Cost/mo | Trade-off |
|---------|---------|-----------|
| Brand24 | $79–$399 | Social listening with X coverage, volume alerts |
| SocialData.tools | $49–$290 | Unofficial X scraping API (ToS risk) |
| Apify Twitter Scrapers | $5–$50 | Web scraping, fragile |

### 11.3 Reddit API

**What it is**: Full API access to posts, comments, subreddits, and trending
content.

**Why it matters**: Reddit is where early adopters discuss new apps before they go
mainstream. Monitoring keyword velocity in subreddits like r/apps, r/iosapps,
r/productivity, r/gaming, r/apple catches trends early.

**Access**: OAuth2 authentication required. Free tier: 100 requests/minute. Reddit
introduced paid tiers in 2023 for commercial/high-volume use (~$0.24 per 1K API
calls for Enterprise).

**What you can track**:
- Search posts/comments by keyword
- Monitor specific subreddits
- Track post velocity, upvote counts, comment counts
- Trending subreddits via `/subreddits/popular`

**Python library**: `praw` (Python Reddit API Wrapper) — mature, well-maintained.
Also `asyncpraw` for async. Every subreddit also has a free RSS feed:
`https://www.reddit.com/r/{sub}/.rss`

**Freshness**: Near real-time (seconds to minutes).

### 11.4 Product Hunt API

**What it is**: GraphQL API for the daily product launch leaderboard.

**Why it matters**: Product Hunt is *the* launchpad for new apps and tools. A
product trending on PH often sees an App Store download spike within 24–72 hours.
Especially relevant for productivity, developer tools, AI tools, and indie apps.

**Access**: Free. Requires OAuth2 token from producthunt.com developer settings.
Rate limit: ~900 requests/15 minutes (cost-based GraphQL system).

**What you can track**:
- Daily top posts ranked by upvotes (the core "trending" metric)
- New product launches in real-time
- Filter by topic/category ("iOS", "Productivity", "Developer Tools")
- Upvote counts, comment counts, maker information

**Python library**: No official SDK. Use `gql` (GraphQL client) or raw `requests`.

**Freshness**: Real-time. Products posted daily, leaderboard updates live.

### 11.5 Hacker News (Algolia API)

**What it is**: Two APIs — the official Firebase API and the Algolia full-text
search API.

**Why it matters**: If an app or tool hits the HN front page, it signals a tech
trend. Highly relevant for developer tools, AI apps, and productivity tools.

**Access**: Both APIs free, no authentication required.

**Endpoints**:

| API | URL | What It Does |
|-----|-----|-------------|
| Official (Firebase) | `hacker-news.firebaseio.com/v0/` | Top/new/best stories, individual items |
| Algolia Search | `hn.algolia.com/api/v1/search` | Full-text search across all stories and comments |

**Algolia features**:
- Search by keyword with date range, points, comment count filters
- Track mentions of app names over time
- Front page endpoint for current trending
- Results indexed within minutes of posting

**Python library**: Raw `requests` — API is simple REST JSON.

**Freshness**: Real-time (Algolia indexes within minutes of posting).

### 11.6 GDELT (Global Database of Events, Language, and Tone)

**What it is**: Free, open global news monitoring. Covers 300K+ news sources in
100+ languages. Updates every **15 minutes**.

**Why it matters**: Detects when an app breaks into mainstream news coverage. News
coverage → search interest → App Store downloads. Massively underrated and
completely free.

**Access**: Free, no authentication, no API key.
- DOC 2.0 API: `api.gdeltproject.org/api/v2/doc/doc?query=...`
- Also available via BigQuery (Google Cloud free tier: 1TB/month)

**Python library**: `gdeltdoc` for the DOC API, or BigQuery client.

**Freshness**: 15 minutes.

### 11.7 Wikipedia Pageviews API

**What it is**: Free API tracking hourly/daily pageviews for any Wikipedia
article.

**Why it matters**: A pageview spike on an app's Wikipedia page is a strong signal
of mainstream awareness. When people start looking up an app on Wikipedia, it's
crossing over from niche to mainstream.

**Access**: Completely free. No API key. No authentication. Generous rate limits
(recommended max 200 req/sec with proper User-Agent).

**Endpoint**:
```
wikimedia.org/api/rest_v1/metrics/pageviews/per-article/
    en.wikipedia/all-access/all-agents/{article_title}/daily/{start}/{end}
```

Also has "most viewed articles" endpoint for detecting globally trending topics.

**Python library**: `pageviewapi`, or raw `requests`.

**Freshness**: 1–2 hours for pageview data. Daily aggregates available next day.

**Limitation**: Not all apps have Wikipedia pages. Coverage limited to well-known
apps and concepts.

### 11.8 YouTube Data API v3

**What it is**: Google's official API for YouTube video and channel data.

**Why it matters**: App review and tutorial videos are a massive driver of
downloads. Channels like MKBHD, iJustine, etc. can cause download spikes when
they feature apps. Tracking review video velocity for specific app names catches
trends as they build.

**Access**: Free tier with quota. 10,000 units/day (a search = 100 units, so
~100 searches/day free). Additional quota available via Google Cloud.

**What you can track**:
- Search for videos by keyword ("best apps 2026", "[app name] review")
- View counts, like counts, comment counts per video
- Trending videos (`chart=mostPopular`) by region and category
- Channel RSS feeds (free, doesn't count against quota)

**Python library**: `google-api-python-client` (official).

**Freshness**: Real-time for video metadata. Trending list updates multiple times
daily.

### 11.9 News APIs

| Service | Cost | Freshness | Coverage | Notes |
|---------|------|-----------|----------|-------|
| **GDELT** | Free | 15 min | 300K+ sources, 100+ languages | Best free option (see 11.6) |
| **Bing News API** (Azure) | **RETIRED Aug 2025**. Replacement: $35/1K via Azure AI Foundry | N/A | Not a standalone REST API anymore | Use GDELT instead |
| **NewsAPI.org** | Free: 100 req/day (24h delayed). Dev: $449/mo | Free = 24h+. Paid = real-time | 150K+ sources | Paid tier needed for real-time |
| **Google Alerts** | Free | Variable | Google News index | Not an API — email/RSS notifications. Not scalable. |
| **Podcast Index API** | Free, open | Real-time | Podcast ecosystem | Apps featured on podcasts → download spikes |

### 11.10 TikTok

**What it is**: The dominant short-form video platform and arguably the most
powerful trend driver in consumer apps.

**Why it matters**: Apps that go viral on TikTok see immediate App Store spikes.
Hashtags like #app, #musthaveapps, #techtoktips are goldmines. The phrase
"that app everyone's using on TikTok" is a real and measurable phenomenon.

**Access**: Very limited and restrictive.
- **TikTok Research API**: Requires application + approval (weeks/months). Free
  if approved. Provides video metadata, hashtag data, comments. Data typically
  1–3 days delayed.
- **TikTok Marketing API**: For advertisers. Some trending data but ad-focused.
- **Unofficial `TikTokApi`** (Python, by David Teather): Reverse-engineered,
  breaks frequently.
- **Third-party services**: Pentos, Exolyt, TrendTok aggregate TikTok trend data
  (paid).

**Python library**: No official SDK. `TikTokApi` (unofficial, fragile).

**Freshness**: Research API = 1–3 days. Unofficial = near real-time (but fragile).

### 11.11 App Store Native Signals

| Source | Cost | What It Provides | How to Access |
|--------|------|------------------|---------------|
| **iTunes RSS Top Charts** | Free, no auth | Current top free/paid/grossing apps per country, up to 200 | `rss.applemarketingtools.com/api/v2/{country}/apps/top-free/200/apps.json` |
| **App Store Review RSS** | Free, no auth | ~50 most recent reviews per app | `itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json` |
| **Apple Search Ads Dashboard** | Free account (no ad spend needed) | Apple's keyword popularity scores (5–100) | Manual dashboard or unofficial automation |
| **iTunes Search API** | Free, no auth | App metadata by keyword search | Already used by RespectASO |

Review velocity spikes (sudden increase in new reviews for an app) strongly
correlate with download spikes and can be monitored via the review RSS feed.

### 11.12 GitHub Trending

**What it is**: GitHub's trending repositories and the GitHub API.

**Why it matters**: Developer tools that trend on GitHub often become popular apps.
Star velocity (repos gaining stars rapidly) is a hype signal for the developer
tools category.

**Access**: Free. 5,000 requests/hour (authenticated), 60/hour (unauthenticated).
No dedicated "trending" API endpoint — use search sorted by stars and filter by
creation date. Unofficial `github-trending-api` available, or scrape
`github.com/trending`.

**Python library**: `PyGithub`, `ghapi`, or GraphQL via `gql`.

**Freshness**: Real-time for repo data. Trending page updates daily.

### 11.13 Bluesky (AT Protocol)

**What it is**: Decentralized social network with a fully open API.

**Why it matters**: Growing user base (10M+ as of early 2025), skewed toward
tech/media professionals. The open API is a significant advantage over X's
pricing. Good for catching early developer and tech trend signals.

**Access**: Free. Account required for authentication. Moderate rate limits
(evolving).

**What you can track**: Post search, feed generators, trending via community-built
feeds. `app.bsky.unspecced.getPopularFeedGenerators` and search endpoints.

**Python library**: `atproto` (Python AT Protocol SDK) — actively developed.

**Freshness**: Real-time.

### 11.14 Mastodon (ActivityPub)

**What it is**: Federated social network. Every instance has a public API.

**Access**: Free, no authentication needed for public data. Rate limits vary by
instance (typically 300 requests/5 minutes).

**Useful endpoints**:
- `/api/v1/trends/tags` — trending hashtags on the instance
- `/api/v1/trends/statuses` — trending posts
- `/api/v1/trends/links` — trending external links

**Python library**: `Mastodon.py` — well-maintained.

**Freshness**: Real-time.

**Limitation**: Small user base, heavily tech-skewed. Best for catching niche
developer/privacy/FOSS app trends.

### 11.15 Steam Trending

**What it is**: Steam Web API for gaming platform data.

**Why it matters**: Games that trend on Steam often have or get mobile versions.
Useful for predicting gaming app trends specifically.

**Access**: Free, requires API key. 100,000 calls/day.

**What you can track**: Top sellers, most played, trending games. Third-party
SteamSpy provides estimated player counts. Steam Charts tracks concurrent players.

**Python library**: `steam` (unofficial), or raw `requests`.

**Freshness**: Real-time for player counts.

### 11.16 Paid ASO Data Providers

| Service | Starting Cost | Key Data |
|---------|---------------|----------|
| **AppFigures** | ~$9/mo | Keyword rankings, review monitoring, revenue estimates. Most affordable. |
| **AppFollow** | ~$111/mo | Reviews, ratings, keyword rankings, ASO data |
| **42matters** | ~$150/mo | App metadata, SDK intelligence |
| **Sensor Tower** | ~$5K+/yr | Download/revenue estimates, keyword rankings, ad intelligence |
| **data.ai** (App Annie) | Enterprise $$$ | The gold standard but prohibitively expensive |

### 11.17 Exploding Topics & Similar Services

| Service | Cost | API? | What It Does |
|---------|------|------|-------------|
| **Exploding Topics** | $39–$249/mo | No public API | Identifies rapidly growing topics before they peak. Uses Google Trends + Reddit + other sources |
| **Treendly** | Paid | No public API | Trend tracking and forecasting |
| **SparkToro** | $50+/mo | Yes | Audience research and trend analysis |
| **Glimpse** | Chrome extension | No | Enhances Google Trends with absolute volumes |

---

## 12. Recommended Integration Stack

### Zero-Budget Stack (All Free)

Covers the full funnel from early signal to mainstream confirmation:

```
EARLY SIGNAL (hours–days ahead)     GROWING (days ahead)           MAINSTREAM (confirmation)
────────────────────────────────    ──────────────────────────     ────────────────────────
Reddit (praw + RSS)            →    Google Trends (pytrends)   →   iTunes Top Charts RSS
Product Hunt (GraphQL API)     →    YouTube Data API           →   Wikipedia Pageviews
Hacker News (Algolia API)      →    GDELT (15-min news)        →   App Store Review RSS
GitHub Trending                →    Bing News API (1K/mo free)
Bluesky (AT Protocol)
Mastodon (/api/v1/trends)
```

**Coverage per app category**:

| Category | Best Free Sources |
|----------|-------------------|
| Developer Tools | GitHub Trending, HN Algolia, Reddit (r/programming), Product Hunt |
| Productivity | Product Hunt, Reddit (r/productivity, r/apple), YouTube reviews |
| Games | Steam Trending, Reddit (r/iosgaming), YouTube, TikTok (if accessible) |
| Social / Consumer | Reddit, Bluesky, Mastodon, GDELT news, Wikipedia |
| Finance | Reddit (r/investing, r/stocks), HN, GDELT, YouTube |
| Health & Fitness | Reddit, YouTube, GDELT news, Google Trends |

### Production Stack (~$100–200/month)

For reliable, automated trend detection:

| Service | Cost | Role |
|---------|------|------|
| SerpAPI (Google Trends) | $50/mo | Reliable Google Trends data without scraping breakage |
| Brand24 | $79/mo | X/Twitter + social listening with alerts |
| Free APIs above | $0 | Reddit, HN, PH, GDELT, Wikipedia, YouTube, App Store RSS |

### Premium Stack (~$5,000+/month)

For maximum coverage and real-time capability:

| Service | Cost | Role |
|---------|------|------|
| X API Pro | $5,000/mo | Real-time tweet counts, filtered stream |
| SerpAPI | $50/mo | Google Trends |
| AppFigures | $9/mo | App Store keyword rankings |
| Free APIs | $0 | Everything in zero-budget stack |

### Signal Processing Approach

For any stack, the general pattern for detecting emerging trends:

1. **Monitor**: Poll sources on a schedule (every 5–60 min depending on source)
2. **Baseline**: Maintain rolling 7-day average volume for tracked keywords
3. **Detect**: Flag keywords exceeding 2–3x their baseline as "spike"
4. **Correlate**: When a spike appears in 2+ sources, upgrade to "emerging trend"
5. **Act**: Trigger a keyword search in RespectASO to assess difficulty/opportunity
6. **Track**: Add the keyword to auto-refresh for ongoing monitoring

---

## Appendix: Source Code Reference

All algorithm implementations live in a single file:

| Component | File | Lines |
|-----------|------|-------|
| Token normalization | `aso/services.py` | 55–66 |
| Finance intent detection | `aso/services.py` | 20–80 |
| Title evidence scoring | `aso/services.py` | 82–148 |
| Brand keyword detection | `aso/services.py` | 151–218 |
| **PopularityEstimator** | `aso/services.py` | 226–429 |
| ITunesSearchService | `aso/services.py` | 437–549 |
| **DownloadEstimator** | `aso/services.py` | 557–789 |
| **DifficultyCalculator** | `aso/services.py` | 797–2069 |
| — `_compute_raw_difficulty` | `aso/services.py` | 834–1022 |
| — `calculate` (with overrides) | `aso/services.py` | 1024–1326 |
| — `_compute_ranking_tiers` | `aso/services.py` | 1328–1542 |
| — `_tier_highlights` | `aso/services.py` | 1544–1617 |
| — `_generate_insights` | `aso/services.py` | 1619–1734 |
| — `_find_opportunities` | `aso/services.py` | 1736–1852 |
| — `_rating_volume_score` | `aso/services.py` | 1855–1899 |
| — `_review_velocity_score` | `aso/services.py` | 1901–1969 |
| — `_rating_quality_score` | `aso/services.py` | 1971–2012 |
| — `_market_age_score` | `aso/services.py` | 2014–2069 |
