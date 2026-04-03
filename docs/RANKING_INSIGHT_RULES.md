# Ranking Insight Rules

How the human-readable takeaways ("The easiest app to beat has just 41 reviews",
"Sweet Spot", etc.) are generated. These are **not** machine learning or weighted
scores — they are three separate rule-based systems (referred to as "slot
machines") that pattern-match competitor data into predefined sentence templates
using hardcoded `if/elif` chains.

The numeric scores (difficulty 1–100, popularity 5–100) are the sophisticated
part with smooth interpolation, logarithmic bands, and 7-factor weighting. The
text you see in the UI is a simple presentation layer on top of those scores.

---

## Table of Contents

1. [Slot Machine 1: Tier Highlights](#slot-machine-1-tier-highlights)
2. [Slot Machine 2: Score Insights](#slot-machine-2-score-insights)
3. [Slot Machine 3: Targeting Advice Labels](#slot-machine-3-targeting-advice-labels)
4. [How They Connect](#how-they-connect)

---

## Slot Machine 1: Tier Highlights

**Source**: `aso/services.py:1544–1617` (`_tier_highlights`)

Generates the bullet points under "How hard is it to rank?" for each tier
(Top 5, Top 10, Top 20). Operates on the competitor apps within that specific
tier slice.

### Input

The method receives these pre-computed values for one tier:

| Parameter | How It's Computed |
|-----------|-------------------|
| `tier_size` | 5, 10, or 20 (the target tier) |
| `n` | Actual number of apps Apple returned for this tier (may be < tier_size) |
| `min_reviews` | `min(userRatingCount)` across all apps in the tier |
| `weakest_app` | Name of the app with `min_reviews` |
| `median` | Median `userRatingCount` within the tier |
| `weak` | Count of apps with `userRatingCount < 1,000` |
| `fresh` | Count of apps with `releaseDate` within the last 365 days |
| `title_opt` | Count of apps with keyword in `trackName` (exact phrase or all words) |

### Rules

The method produces up to 4 bullet strings, evaluated in order:

#### Rule 0: Open Positions (short-circuit)

If fewer apps exist than the tier size, only this bullet is shown and all
others are skipped.

| Condition | Output |
|-----------|--------|
| `n < tier_size` | "Only {n} app(s) rank here — {open_spots} open spot(s)." |

#### Rule 1: Review Barrier

Exactly one of these fires, based on `min_reviews` (the weakest app in the tier):

| Condition | Output | Implication |
|-----------|--------|-------------|
| `min_reviews < 100` | "The easiest app to beat has just {min_reviews} reviews." | Very low barrier |
| `min_reviews < 1,000` | "You need ~{min_reviews}+ reviews to compete (weakest: {name})." | Low barrier |
| `min_reviews < 10,000` | "You need ~{min_reviews}+ reviews to break in." | Moderate barrier |
| `min_reviews >= 10,000` | "Requires ~{min_reviews}+ reviews — established market." | High barrier |

**Note**: There is no "between 1,000 and 5,000 = quite competitive" band.
The thresholds are 100 / 1,000 / 10,000 — three cutoffs, four bands.

#### Rule 2: Weak Spots

Binary split at the 1,000 review threshold:

| Condition | Output |
|-----------|--------|
| `weak > 0` | "{weak} of {n} apps have under 1K reviews — beatable." |
| `weak == 0` | "Every app here has 1K+ reviews — no easy targets." |

#### Rule 3: Fresh Entrants (conditional)

Only appears if at least one app was released in the last 12 months:

| Condition | Output |
|-----------|--------|
| `fresh > 0` | "{fresh} app(s) broke in within the last year." |
| `fresh == 0` | *(no bullet shown)* |

#### Rule 4: Title Keyword Usage

Exactly one of these fires:

| Condition | Output |
|-----------|--------|
| `title_opt == 0` | "No app uses this exact keyword in its title — ASO opportunity!" |
| `title_opt < n // 2` | "Only {title_opt} of {n} apps use this keyword in their title." |
| `title_opt >= n // 2` | "{title_opt} of {n} apps already target this keyword in their title." |

### Example Output (Top 5, keyword "pilates")

```
- The easiest app to beat has just 41 reviews.
- 4 of 5 apps have under 1K reviews — beatable.
- 1 app broke in within the last year.
- Only 2 of 5 apps use this keyword in their title.
```

---

## Slot Machine 2: Score Insights

**Source**: `aso/services.py:1619–1734` (`_generate_insights`)

Generates the insight pills with icons that appear in the difficulty breakdown
section. These explain *why* the difficulty score is what it is. Each rule fires
independently — multiple insights can appear simultaneously.

### Input

| Parameter | How It's Computed |
|-----------|-------------------|
| `rating_counts` | List of `userRatingCount` for all competitors |
| `median` | Median of `rating_counts` |
| `avg` | Mean of `rating_counts` |
| `serious` | Count of apps with > 10,000 reviews |
| `mega` | Count of top-half apps with > 100,000 reviews |
| `ultra` | Count of top-half apps with > 1,000,000 reviews |
| `title_matches` | Count of apps with keyword in title |
| `n` | Total number of competitors |
| `avg_quality` | Log-weighted average star rating (see difficulty factor 4) |

### Rules

#### Insight 1: Dominant Brands (mutually exclusive)

| Condition | Icon | Type | Output |
|-----------|------|------|--------|
| `ultra > 0` | 🏢 | barrier | "{ultra} app(s) with 1M+ reviews — dominated by major brands" |
| `mega > 0` (and no ultra) | ⚠️ | barrier | "{mega} app(s) with 100K+ reviews — strong incumbents" |
| Neither | | | *(no insight)* |

Only the top half of competitors is checked for mega/ultra counts. This prevents
tail-position backfill apps from triggering false "dominated" warnings.

#### Insight 2: Review Distribution Skew

| Condition | Icon | Type | Output |
|-----------|------|------|--------|
| `avg > median * 3` (and both > 0) | 📊 | info | "Review distribution is skewed — median ({median}) is much lower than mean ({avg}). A few giants inflate the average." |

This fires when a handful of mega-apps pull the average far above the median,
indicating that most competitors are actually much weaker than the average
suggests.

#### Insight 3: Title Relevance

Exactly one fires:

| Condition | Icon | Type | Output |
|-----------|------|------|--------|
| `title_matches == 0` | 🎯 | opportunity | "No competitors have this exact keyword in their title — potential title optimization gap" |
| `title_matches <= 2` | 🎯 | opportunity | "Only {title_matches} of {n} competitors use this keyword in their title" |
| `title_matches > 2` | 🔒 | barrier | "{title_matches} of {n} competitors already have this keyword in their title" |

#### Insight 4: Quality Bar

| Condition | Icon | Type | Output |
|-----------|------|------|--------|
| `avg_quality >= 4.5` | ⭐ | barrier | "High quality bar — avg rating is {avg_quality} stars. Users expect excellence." |

This uses the log-weighted average (not simple mean), so a 5.0-star app with 1
review doesn't outweigh a 4.3-star app with 50,000 reviews.

#### Insight 5: Beatable Competitors

| Condition | Icon | Type | Output |
|-----------|------|------|--------|
| `weak_count >= 3` (apps with < 1,000 reviews) | 💡 | opportunity | "{weak_count} of {n} competitors have <1,000 reviews — beatable with a quality app" |

This only fires when 3 or more apps are weak, signaling a realistic opening.

### Insight Types

Each insight is tagged with a `type` that controls how it's styled in the UI:

| Type | Meaning | UI Style |
|------|---------|----------|
| `barrier` | Something that makes ranking harder | Red/warning tone |
| `opportunity` | Something that makes ranking easier | Green/positive tone |
| `info` | Neutral context | Grey/informational tone |

### Post-Processing: Backfill Recontextualization

**Source**: `aso/services.py:1259–1280`

When the overall difficulty score is adjusted downward due to Apple backfill
detection (weak leader + low title match ratio), insights that describe backfill
apps as real competitors are amended:

| Original Insight | Amended |
|------------------|---------|
| "100K+ reviews — strong incumbents" | "100K+ reviews — strong incumbents (but most are backfill, not targeting this keyword)" |
| "High quality bar — avg rating is 4.7 stars. Users expect excellence." | Same text + "(but most are backfill, not targeting this keyword)" |

This only happens when `match_ratio <= 0.3` and the override reason is
`weak_leader` or `backfill`.

---

## Slot Machine 3: Targeting Advice Labels

**Source**: `aso/models.py:191–234` (`targeting_advice` property on `SearchResult`)

Generates the colored badge label ("Sweet Spot", "Avoid", etc.) shown next to
each search result in the dashboard. This is a 2D decision grid mapping
popularity score vs difficulty score to a label.

### Decision Grid (with popularity data)

When `popularity_score` is not None:

```
                         Difficulty Score
                   ≤ 40         ≤ 60          > 60
              ┌────────────┬────────────┬─────────────┐
  Pop ≥ 40    │ 🎯 Sweet   │ ✅ Good     │ ⚔️ Worth     │
              │    Spot     │    Target   │   Competing  │
              ├────────────┼────────────┼─────────────┤
  Pop 30–39   │ 💎 Hidden  │ 👍 Decent   │ ⚔️ Challen-  │
              │    Gem      │    Option   │   ging       │
              ├────────────┼────────────┼─────────────┤
  Pop < 30    │ 🔍 Low     │ 🚫 Avoid   │ 🚫 Avoid    │
              │    Volume   │            │              │
              └────────────┴────────────┴─────────────┘
```

#### Exact Thresholds

| Label | Icon | Popularity | Difficulty | Description |
|-------|------|-----------|------------|-------------|
| **Sweet Spot** | 🎯 | >= 40 | <= 40 | "High popularity + low difficulty — ideal keyword to target with good ASO." |
| **Good Target** | ✅ | >= 40 | 41–60 | "Solid popularity with manageable difficulty." |
| **Worth Competing** | ⚔️ | >= 40 | > 60 | "High demand but tough competition. Consider long-tail variants." |
| **Hidden Gem** | 💎 | 30–39 | <= 40 | "Moderate volume with little competition. Good for niche apps." |
| **Decent Option** | 👍 | 30–39 | 41–60 | "Moderate demand and competition. Can work as a supporting keyword." |
| **Low Volume** | 🔍 | < 30 | <= 30 | "Easy to rank but few people search for this. Best as a supporting keyword." |
| **Avoid** | 🚫 | < 30 | > 30 | "Low search volume with notable competition." |
| **Challenging** | ⚔️ | (fallthrough) | (fallthrough) | "Strong competition. Focus on long-tail variants." |

### Decision Grid (without popularity data)

When `popularity_score` is None (no competitor data to estimate popularity),
a simpler difficulty-only grid is used:

| Label | Icon | Difficulty | Description |
|-------|------|-----------|-------------|
| **Easy to Rank** | 🟢 | <= 25 | "Low competition — a well-optimized app can rank quickly." |
| **Moderate** | 🟡 | 26–50 | "Achievable with strong ASO." |
| **Competitive** | 🟠 | 51–75 | "Consider long-tail variants." |
| **Very Competitive** | 🔴 | > 75 | "Dominated by established apps. Target easier keywords first." |

### Output Format

The property returns a 4-tuple:

```python
(icon, label, css_classes, description)
# Example: ("🎯", "Sweet Spot", "bg-green-900/20 text-green-300 border-green-500/20",
#           "High popularity + low difficulty — ideal keyword to target with good ASO.")
```

---

## How They Connect

All three slot machines operate on the same underlying data but at different
levels of abstraction:

```
iTunes Search API response
  └─ 25 competitor app dicts (trackName, userRatingCount, averageUserRating, releaseDate, sellerName, ...)
       │
       ├─── DifficultyCalculator.calculate()
       │      ├─── 7 weighted factors → difficulty score (1–100)
       │      ├─── _generate_insights()  ──────────────── SLOT MACHINE 2 (insight pills)
       │      ├─── _find_opportunities() ──────────────── (opportunity signals, not covered here)
       │      └─── _compute_ranking_tiers()
       │             └─── _tier_highlights() ──────────── SLOT MACHINE 1 (tier bullets)
       │
       ├─── PopularityEstimator.estimate()
       │      └─── 6 signals → popularity score (5–100)
       │
       └─── SearchResult.targeting_advice (property)
              └─── popularity × difficulty grid ────────── SLOT MACHINE 3 (badge label)
```

**Slot Machine 1** (tier highlights) operates on the raw competitor data within
each tier slice — it directly inspects `userRatingCount`, `releaseDate`, and
`trackName` of the top 5/10/20 apps.

**Slot Machine 2** (score insights) operates on aggregate statistics computed
during the difficulty calculation — median, mean, counts of mega/ultra apps,
title match counts, and the log-weighted quality average.

**Slot Machine 3** (targeting advice) operates only on the two final numeric
scores — popularity and difficulty. It never looks at individual competitors.
It's the simplest of the three: a 2D lookup table.

None of the three systems influence the numeric scores. They are a read-only
presentation layer — if you removed all three, the difficulty score, popularity
score, and download estimates would be identical.
