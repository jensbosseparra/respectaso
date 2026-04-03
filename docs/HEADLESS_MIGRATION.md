# Headless Migration Guide

How to extract RespectASO's core keyword analysis engine and integrate it into
another project — specifically a FastAPI + PostgreSQL (Neon) backend — without
the Django UI, desktop wrapper, or SQLite database.

---

## Table of Contents

1. [Current Project Anatomy](#1-current-project-anatomy)
2. [What You Keep vs What You Drop](#2-what-you-keep-vs-what-you-drop)
3. [Core Engine Extraction](#3-core-engine-extraction)
4. [Django vs FastAPI Migration](#4-django-vs-fastapi-migration)
5. [Database Migration: SQLite → PostgreSQL](#5-database-migration-sqlite--postgresql)
6. [Headless API Design](#6-headless-api-design)
7. [LLM-Driven Keyword Generation](#7-llm-driven-keyword-generation)
8. [Integration with Existing FastAPI Project](#8-integration-with-existing-fastapi-project)
9. [What You Lose](#9-what-you-lose)
10. [Migration Checklist](#10-migration-checklist)

---

## 1. Current Project Anatomy

### File Count by Category

| Category | Files | Lines | Purpose |
|----------|-------|-------|---------|
| **Core Engine** | 1 file | 2,068 | `aso/services.py` — all scoring algorithms |
| **Models** | 1 file | 234 | `aso/models.py` — Django ORM (App, Keyword, SearchResult) |
| **Views** | 1 file | 1,186 | `aso/views.py` — HTTP handlers (HTML + JSON) |
| **Scheduler** | 1 file | 221 | `aso/scheduler.py` — background auto-refresh |
| **Forms** | 1 file | 115 | `aso/forms.py` — Django form validation |
| **Template Tags** | 1 file | 368 | `aso/templatetags/aso_tags.py` — display filters |
| **Templates (UI)** | 7 files | ~1,725 | `aso/templates/aso/` — Django HTML + Tailwind + vanilla JS |
| **Django Config** | 5 files | ~170 | `core/` — settings, urls, wsgi, context processors |
| **Desktop Wrapper** | 3 files | ~250 | `desktop/` — pywebview macOS app |
| **Migrations** | 6 files | ~200 | `aso/migrations/` — Django schema evolution |
| **Static Assets** | 9 files | — | Favicons, logos, manifest |
| **Docker/Deploy** | 4 files | ~80 | Dockerfile, compose, entrypoint, spec |
| **Admin** | 1 file | 29 | `aso/admin.py` — Django admin registration |

**Total**: ~6,600 lines across ~40 meaningful files.

### Dependency Graph

```
services.py (CORE ENGINE)
  ├── depends on: requests, math, re, datetime (stdlib + 1 pip package)
  ├── NO dependency on Django
  ├── NO dependency on models.py
  └── NO dependency on any other project file

models.py (DATA LAYER)
  ├── depends on: Django ORM
  └── references: services.py (indirectly, via views)

views.py (HTTP LAYER)
  ├── depends on: Django, models.py, services.py, forms.py, scheduler.py
  └── mixes HTML rendering + JSON API

scheduler.py (BACKGROUND JOBS)
  ├── depends on: Django ORM (models), services.py
  └── runs in daemon thread

templates/ (UI)
  ├── depends on: Django template engine, templatetags
  └── pure presentation (no business logic)

desktop/ (NATIVE APP)
  ├── depends on: Django, pywebview
  └── just a wrapper that starts Django + opens a WebKit window
```

**Key insight: `services.py` has ZERO Django dependencies.** It's pure Python
with only `requests`, `math`, `re`, `datetime`, and `logging`. It can be
extracted as-is into any Python project.

---

## 2. What You Keep vs What You Drop

### KEEP (Essential for Headless)

| File | Lines | Why |
|------|-------|-----|
| `aso/services.py` | 2,068 | **The entire engine.** All 4 classes: `ITunesSearchService`, `PopularityEstimator`, `DifficultyCalculator`, `DownloadEstimator`. Plus helper functions for title matching, brand detection, finance disambiguation. |
| `aso/scheduler.py` | 221 | Background refresh logic. Needs adaptation (replace Django ORM calls with SQLAlchemy/asyncpg) but the scheduling logic is reusable. |
| `aso/models.py` | 234 | Schema reference only. You'll rewrite these as SQLAlchemy models or Pydantic schemas, but the field definitions and relationships are the blueprint. |

### DROP (Not Needed for Headless)

| File/Folder | Lines | Why Not Needed |
|-------------|-------|----------------|
| `aso/views.py` | 1,186 | Django-specific HTTP handlers. You'll write new FastAPI endpoints. |
| `aso/forms.py` | 115 | Django form validation. Replaced by Pydantic models in FastAPI. |
| `aso/templates/` | ~1,725 | Django HTML templates. Headless = no server-rendered UI. |
| `aso/templatetags/` | 368 | Template display filters. Not needed without templates. |
| `aso/admin.py` | 29 | Django admin. Replaced by Starlette Admin in your FastAPI project. |
| `core/` | ~170 | Django project config. Not applicable to FastAPI. |
| `desktop/` | ~250 | macOS pywebview wrapper. Not needed. |
| `static/` | — | Favicons/logos for web UI. |
| `Dockerfile`, `docker-compose.yml` | ~30 | Docker config. You'll have your own. |
| `aso/migrations/` | ~200 | Django migrations. You'll use Alembic with SQLAlchemy. |

### Summary

```
KEEP:   2,068 lines  (services.py — copy as-is)
ADAPT:    455 lines  (scheduler.py + models.py — rewrite for SQLAlchemy)
DROP:  ~4,077 lines  (everything else)
```

**You are migrating ~2,500 lines of meaningful logic, of which 2,068 lines
require zero changes.**

---

## 3. Core Engine Extraction

### Step 1: Copy services.py

```bash
# From the respectaso repo
cp aso/services.py /your-fastapi-project/app/aso/services.py
```

This file works standalone. Test it:

```python
from aso.services import (
    ITunesSearchService,
    PopularityEstimator,
    DifficultyCalculator,
    DownloadEstimator,
)

itunes = ITunesSearchService()
popularity = PopularityEstimator()
difficulty = DifficultyCalculator()
downloads = DownloadEstimator()

# Search for a keyword
competitors = itunes.search_apps("pilates", country="us", limit=25)

# Get scores
pop_score = popularity.estimate(competitors, "pilates")
diff_score, breakdown = difficulty.calculate(competitors, keyword="pilates")
dl_estimates = downloads.estimate(pop_score or 0, country="us")

print(f"Popularity: {pop_score}")
print(f"Difficulty: {diff_score} ({breakdown['interpretation']})")
print(f"Daily searches (US): {dl_estimates['daily_searches']}")
```

**Only dependency**: `pip install requests`

### Step 2: Create Pydantic Schemas

Replace Django models with Pydantic + SQLAlchemy:

```python
# app/aso/schemas.py
from pydantic import BaseModel
from datetime import datetime

class KeywordSearchRequest(BaseModel):
    keywords: list[str]           # ["pilates", "yoga mat", "stretching"]
    countries: list[str] = ["us"] # max 5
    app_track_id: int | None = None

class KeywordScore(BaseModel):
    keyword: str
    country: str
    popularity_score: int | None
    difficulty_score: int
    difficulty_label: str         # "Very Easy" ... "Extreme"
    daily_searches: float
    download_estimates: dict
    competitors_count: int
    app_rank: int | None
    breakdown: dict
    searched_at: datetime
    first_seen_at: datetime | None  # for trend tracking

class KeywordSearchResponse(BaseModel):
    results: list[KeywordScore]
    keywords_searched: int
    countries_searched: int
```

### Step 3: Create SQLAlchemy Models

```python
# app/aso/models.py
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime, timezone

class ASOApp(Base):
    __tablename__ = "aso_apps"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    bundle_id = Column(String(200), nullable=True)
    track_id = Column(Integer, unique=True, nullable=True)
    store_url = Column(String(500), nullable=True)
    icon_url = Column(String(500), nullable=True)
    seller_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    keywords = relationship("ASOKeyword", back_populates="app")

class ASOKeyword(Base):
    __tablename__ = "aso_keywords"

    id = Column(Integer, primary_key=True)
    keyword = Column(String(200), nullable=False)
    app_id = Column(Integer, ForeignKey("aso_apps.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    app = relationship("ASOApp", back_populates="keywords")
    results = relationship("ASOSearchResult", back_populates="keyword_rel")

    __table_args__ = (
        UniqueConstraint("keyword", "app_id", name="uq_keyword_app"),
    )

class ASOSearchResult(Base):
    __tablename__ = "aso_search_results"

    id = Column(Integer, primary_key=True)
    keyword_id = Column(Integer, ForeignKey("aso_keywords.id", ondelete="CASCADE"))
    popularity_score = Column(Integer, nullable=True)
    difficulty_score = Column(Integer, nullable=False)
    difficulty_breakdown = Column(JSON)
    competitors_data = Column(JSON)
    app_rank = Column(Integer, nullable=True)
    country = Column(String(5), default="us")
    searched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    keyword_rel = relationship("ASOKeyword", back_populates="results")
```

---

## 4. Django vs FastAPI Migration

### What Changes

| Aspect | Django (Current) | FastAPI (Target) |
|--------|-----------------|------------------|
| **ORM** | Django ORM | SQLAlchemy 2.0 + asyncpg |
| **Validation** | Django Forms | Pydantic models |
| **HTTP** | Django views + `@require_POST` | FastAPI routes + `@router.post` |
| **Background Jobs** | Daemon thread + `threading.Lock` | `asyncio.create_task` or Celery or APScheduler |
| **Admin** | Django Admin (`/admin/`) | Starlette Admin (already in your project) |
| **Templates** | Django template engine | Not needed (headless) |
| **Database** | SQLite (file) | PostgreSQL on Neon |
| **Migrations** | Django migrations | Alembic |
| **Static Files** | WhiteNoise | Not needed (headless) |
| **CSRF** | Django middleware | Not needed (API-only, use JWT/API keys) |
| **Sessions** | Django sessions | Not needed |

### What Does NOT Change

| Aspect | Notes |
|--------|-------|
| **`services.py`** | Zero changes. Pure Python. Works in any framework. |
| **iTunes API calls** | Same `requests.get()` calls. No framework dependency. |
| **Scoring algorithms** | Identical. All math is in `services.py`. |
| **Data schema** | Same 3 tables (App, Keyword, SearchResult). Just different ORM. |

### Effort Estimate

| Task | Complexity | Notes |
|------|-----------|-------|
| Copy `services.py` | Trivial | Copy-paste, zero changes |
| Write SQLAlchemy models | Low | 3 models, straightforward mapping |
| Write Alembic migration | Low | Auto-generated from models |
| Write FastAPI endpoints | Medium | ~200 lines to replace ~1,186 lines of views.py (most of views.py is HTML rendering) |
| Adapt scheduler | Medium | Replace Django ORM queries with SQLAlchemy async |
| Write Pydantic schemas | Low | ~50 lines |
| Starlette Admin views | Low | Register 3 models, add keyword input form |
| **Total** | **~500 new lines** | Replacing ~4,000+ lines (most of which is UI/Django boilerplate you don't need) |

---

## 5. Database Migration: SQLite → PostgreSQL

### Schema Mapping

The Django models map directly to PostgreSQL:

```sql
-- PostgreSQL schema (Neon)

CREATE TABLE aso_apps (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    bundle_id       VARCHAR(200),
    track_id        INTEGER UNIQUE,
    store_url       VARCHAR(500),
    icon_url        VARCHAR(500),
    seller_name     VARCHAR(200),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE aso_keywords (
    id              SERIAL PRIMARY KEY,
    keyword         VARCHAR(200) NOT NULL,
    app_id          INTEGER REFERENCES aso_apps(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(keyword, app_id)
);

CREATE TABLE aso_search_results (
    id                    SERIAL PRIMARY KEY,
    keyword_id            INTEGER NOT NULL REFERENCES aso_keywords(id) ON DELETE CASCADE,
    popularity_score      INTEGER,
    difficulty_score      INTEGER NOT NULL,
    difficulty_breakdown  JSONB,
    competitors_data      JSONB,
    app_rank              INTEGER,
    country               VARCHAR(5) DEFAULT 'us',
    searched_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_search_results_keyword ON aso_search_results(keyword_id);
CREATE INDEX idx_search_results_country ON aso_search_results(country);
CREATE INDEX idx_search_results_date ON aso_search_results(searched_at);

-- For trend signal integration (from TREND_SIGNALS_ROADMAP.md)
CREATE TABLE aso_trend_signals (
    id                SERIAL PRIMARY KEY,
    source            VARCHAR(50) NOT NULL,
    keyword           VARCHAR(500) NOT NULL,
    raw_volume        REAL,
    normalized_score  REAL,
    country           VARCHAR(5) DEFAULT 'us',
    metadata          JSONB,
    first_seen_at     TIMESTAMPTZ NOT NULL,
    collected_at      TIMESTAMPTZ NOT NULL,
    date_stamp        DATE NOT NULL,
    UNIQUE(source, keyword, country, date_stamp)
);

CREATE INDEX idx_trend_keyword ON aso_trend_signals(keyword);
CREATE INDEX idx_trend_first_seen ON aso_trend_signals(first_seen_at);
```

### Key Differences from SQLite

| SQLite (Current) | PostgreSQL (Target) | Notes |
|-----------------|---------------------|-------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` | Auto-increment |
| `JSON` field | `JSONB` | PostgreSQL's binary JSON — indexable, queryable |
| `DATETIME` | `TIMESTAMPTZ` | Timezone-aware timestamps |
| Single-file DB | Connection pooling (asyncpg) | Use `databases` or `sqlalchemy[asyncio]` |
| No concurrent writes | Full ACID concurrency | Multiple users/workers safe |

### Neon-Specific Notes

- Neon is serverless PostgreSQL — connections may be cold-started
- Use connection pooling (`pgbouncer` built into Neon)
- Set `sslmode=require` in connection string
- Neon supports branching — use a dev branch for testing migrations

---

## 6. Headless API Design

### FastAPI Endpoints

These replace the 20+ Django views with a minimal JSON-only API:

```python
# app/aso/router.py
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.aso.services import (
    ITunesSearchService, PopularityEstimator,
    DifficultyCalculator, DownloadEstimator,
)
from app.aso.schemas import KeywordSearchRequest, KeywordSearchResponse
from app.database import get_session

router = APIRouter(prefix="/aso", tags=["ASO"])

@router.post("/search", response_model=KeywordSearchResponse)
async def search_keywords(
    req: KeywordSearchRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Search 1-20 keywords across 1-5 countries.
    Returns popularity, difficulty, download estimates per keyword+country.
    """
    itunes = ITunesSearchService()
    popularity_est = PopularityEstimator()
    difficulty_calc = DifficultyCalculator()
    download_est = DownloadEstimator()

    results = []
    for keyword in req.keywords[:20]:
        for country in req.countries[:5]:
            competitors = itunes.search_apps(keyword, country=country, limit=25)
            pop = popularity_est.estimate(competitors, keyword)
            diff, breakdown = difficulty_calc.calculate(competitors, keyword=keyword)
            dl = download_est.estimate(pop or 0, country=country)

            app_rank = None
            if req.app_track_id:
                app_rank = itunes.find_app_rank(keyword, req.app_track_id, country)

            results.append({
                "keyword": keyword,
                "country": country,
                "popularity_score": pop,
                "difficulty_score": diff,
                "difficulty_label": breakdown["interpretation"],
                "daily_searches": dl["daily_searches"],
                "download_estimates": dl["tiers"],
                "competitors_count": len(competitors),
                "app_rank": app_rank,
                "breakdown": breakdown,
                "searched_at": datetime.now(timezone.utc),
            })

            # Persist to DB (async)
            await _save_result(session, keyword, country, pop, diff, breakdown, competitors, app_rank)

            time.sleep(2)  # Rate limit iTunes API

    return KeywordSearchResponse(
        results=results,
        keywords_searched=len(req.keywords),
        countries_searched=len(req.countries),
    )

@router.get("/history")
async def get_history(
    keyword: str | None = None,
    country: str | None = None,
    days: int = 30,
    session: AsyncSession = Depends(get_session),
):
    """Get search history with optional filters."""
    ...

@router.post("/opportunity")
async def opportunity_search(
    keyword: str,
    app_track_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Search a keyword across all 30 countries."""
    ...
```

### What the API Returns

For a search like `POST /aso/search` with `{"keywords": ["pilates"], "countries": ["us"]}`:

```json
{
    "results": [
        {
            "keyword": "pilates",
            "country": "us",
            "popularity_score": 72,
            "difficulty_score": 61,
            "difficulty_label": "Hard",
            "daily_searches": 825.0,
            "download_estimates": {
                "top_5": {"low": 5.94, "high": 23.76},
                "top_6_10": {"low": 1.13, "high": 4.52},
                "top_11_20": {"low": 0.26, "high": 1.03}
            },
            "competitors_count": 25,
            "app_rank": null,
            "breakdown": {
                "total_score": 61,
                "rating_volume": 72.3,
                "review_velocity": 45.1,
                "dominant_players": 58.7,
                "rating_quality": 81.2,
                "market_age": 65.0,
                "publisher_diversity": 88.0,
                "title_relevance": 60.0,
                "interpretation": "Hard",
                "insights": [...],
                "opportunity_signals": [...],
                "ranking_tiers": {
                    "top_5":  {"tier_score": 71, "label": "Hard", ...},
                    "top_10": {"tier_score": 65, "label": "Hard", ...},
                    "top_20": {"tier_score": 61, "label": "Hard", ...}
                }
            },
            "searched_at": "2026-03-29T15:00:00Z"
        }
    ],
    "keywords_searched": 1,
    "countries_searched": 1
}
```

---

## 7. LLM-Driven Keyword Generation

### Workflow

```
User Input (Starlette Admin or API)
  "pilates for beginners"
       ↓
  LLM generates semantic keywords
       ↓
  ["pilates", "pilates workout", "pilates app",
   "yoga pilates", "core workout", "stretching exercises",
   "flexibility training", "mat exercises", "body toning",
   "home workout pilates", "pilates for back pain"]
       ↓
  Feed each keyword into services.py engine
       ↓
  Score all keywords across specified countries
       ↓
  Return ranked results sorted by opportunity
  (high popularity + low difficulty = sweet spot)
```

### LLM Prompt Template

```python
KEYWORD_GENERATION_PROMPT = """
You are an App Store Optimization expert. Given a topic or concept,
generate 15-25 keywords that iOS users would search for in the App Store.

Topic: {topic}
Country: {country}

Rules:
- Include 1-word, 2-word, and 3-word variations
- Include synonyms and related concepts
- Include "app" suffix variations (e.g., "pilates app")
- Include intent-based keywords (e.g., "pilates for beginners")
- Include competitor-adjacent keywords
- Focus on keywords people actually type in the App Store search bar
- Order by estimated search volume (highest first)

Return as a JSON array of strings, nothing else.
"""
```

### Integration with Trend Signals

When trend signals detect an emerging keyword (from TREND_SIGNALS_ROADMAP.md):

```python
async def analyze_trending_keyword(keyword: str, countries: list[str]):
    """
    Called when correlation engine detects an emerging trend.
    1. Generate semantic variations via LLM
    2. Score all variations across target countries
    3. Store results with trend signal context
    4. Return ranked opportunities
    """
    # Generate variations
    variations = await llm_generate_keywords(keyword)

    # Score each variation
    results = []
    for kw in variations:
        for country in countries:
            score = await score_keyword(kw, country)
            score["trend_source"] = get_trend_source(kw)  # which signal detected it
            score["first_seen_at"] = get_first_seen(kw)    # when it first appeared
            results.append(score)

    # Sort by opportunity (high pop + low difficulty)
    results.sort(key=lambda r: (r["popularity_score"] or 0) - r["difficulty_score"], reverse=True)
    return results
```

---

## 8. Integration with Existing FastAPI Project

### Folder Structure in Your FastAPI Project

```
your-fastapi-project/
  app/
    aso/                        # ASO module (self-contained)
      __init__.py
      services.py               # COPIED FROM RESPECTASO (2,068 lines, zero changes)
      models.py                 # SQLAlchemy models (new, ~60 lines)
      schemas.py                # Pydantic models (new, ~50 lines)
      router.py                 # FastAPI endpoints (new, ~200 lines)
      scheduler.py              # Adapted from RespectASO (~150 lines)
      keywords.py               # LLM keyword generation (new, ~80 lines)
    signals/                    # Trend signal modules (from TREND_SIGNALS_ROADMAP.md)
      google_trends/
      reddit/
      ...
    search_ads/                 # Your existing Search Ads integration
    app_store_connect/          # Your existing ASC integration
    database.py                 # Async SQLAlchemy session
    main.py                     # FastAPI app
```

### Mounting the ASO Router

```python
# app/main.py
from fastapi import FastAPI
from app.aso.router import router as aso_router

app = FastAPI()
app.include_router(aso_router)
```

### Starlette Admin Integration

```python
# app/admin.py
from starlette_admin import ModelView
from app.aso.models import ASOApp, ASOKeyword, ASOSearchResult

class ASOKeywordAdmin(ModelView):
    """
    Admin view with keyword input field.
    Supports comma-separated keywords and triggers analysis.
    """
    fields = ["keyword", "app", "created_at"]
    # Add custom action for bulk keyword analysis

class ASOSearchResultAdmin(ModelView):
    fields = [
        "keyword_rel", "country", "popularity_score",
        "difficulty_score", "app_rank", "searched_at"
    ]
    list_filter = ["country"]
    sortable_fields = ["popularity_score", "difficulty_score", "searched_at"]
```

---

## 9. What You Lose

### Losing the Django UI

| Feature in Django UI | Headless Replacement |
|---------------------|---------------------|
| Dashboard with search bar | API endpoint + Starlette Admin form |
| Visual competitor cards | JSON response (render in your own UI or feed to LLM) |
| Sorting/filtering table | SQL queries with `ORDER BY` / `WHERE` |
| Trend arrows (↑↓) | Compare `searched_at` timestamps in DB |
| Insight pills (Sweet Spot, etc.) | `breakdown.insights` in JSON response (still computed) |
| Country opportunity heatmap | JSON per-country scores (render in your own UI) |
| CSV export | `SELECT ... INTO CSV` or pandas DataFrame |
| Auto-refresh progress bar | Background task status endpoint |
| Version check banner | Not needed (your app has its own deployment) |

### What You Keep (Nothing Lost from the Engine)

All scoring logic is preserved:
- 6-signal popularity estimation (5–100)
- 7-factor difficulty calculation (1–100) with all sub-scores
- Download estimation with TTR curves and market multipliers
- Ranking tier analysis (Top 5 / Top 10 / Top 20)
- Brand keyword detection
- Finance intent disambiguation
- Apple backfill correction (3 overrides)
- Opportunity signals (title gap, weak competitors, fresh entrants, cross-genre)
- All 40+ country market size multipliers

### Net Assessment

```
LOST:
- Django server-rendered HTML/CSS/JS (1,725 lines of templates)
- Django template tags (368 lines)
- Django forms (115 lines)
- Django admin (29 lines)
- Desktop pywebview wrapper (250 lines)
- Django config (170 lines)
Total: ~2,657 lines of framework-specific code

KEPT:
- Core engine: services.py (2,068 lines, zero changes)
- All algorithms, all scores, all calibration data
- iTunes API integration
- Background refresh logic (adapted)

WRITTEN NEW:
- SQLAlchemy models (~60 lines)
- Pydantic schemas (~50 lines)
- FastAPI endpoints (~200 lines)
- Scheduler adaptation (~150 lines)
- LLM keyword generation (~80 lines)
Total: ~540 new lines

NET: You replace ~2,657 lines of Django UI/config with ~540 lines of
FastAPI code. The 2,068-line engine is a direct copy.
```

---

## 10. Migration Checklist

### Phase 1: Engine Extraction (1 day)

- [ ] Copy `aso/services.py` to your FastAPI project
- [ ] Verify it works standalone: `python -c "from aso.services import ITunesSearchService; print(ITunesSearchService().search_apps('test'))"`
- [ ] Add `requests>=2.32.0` to your project's requirements

### Phase 2: Database Setup (1 day)

- [ ] Create SQLAlchemy models (ASOApp, ASOKeyword, ASOSearchResult)
- [ ] Create Alembic migration
- [ ] Run migration against Neon PostgreSQL
- [ ] Add `aso_trend_signals` table for future trend integration

### Phase 3: API Endpoints (2 days)

- [ ] Write `POST /aso/search` endpoint (keyword search)
- [ ] Write `GET /aso/history` endpoint (search history)
- [ ] Write `POST /aso/opportunity` endpoint (multi-country scan)
- [ ] Write Pydantic request/response schemas
- [ ] Add 2-second rate limiting between iTunes API calls

### Phase 4: Admin Integration (1 day)

- [ ] Register ASO models in Starlette Admin
- [ ] Add keyword input form (comma-separated or single)
- [ ] Add search trigger action (runs analysis on input keywords)
- [ ] Add results view with sorting by popularity/difficulty

### Phase 5: LLM Integration (1 day)

- [ ] Write keyword generation prompt
- [ ] Connect to your LLM provider (Claude API, etc.)
- [ ] Wire LLM output → keyword search pipeline
- [ ] Add "Analyze Topic" action in admin

### Phase 6: Background Scheduler (1 day)

- [ ] Adapt `scheduler.py` for async SQLAlchemy
- [ ] Configure refresh frequency (daily)
- [ ] Add 90-day result cleanup
- [ ] Wire status reporting to admin

### Total Estimated Effort: ~7 working days

---

## Appendix: services.py Class Reference

Quick reference for what's available in the engine you're copying:

### ITunesSearchService

```python
itunes = ITunesSearchService()
apps = itunes.search_apps("pilates", country="us", limit=25)  # → list[dict]
app = itunes.lookup_by_id(123456789, country="us")             # → dict | None
rank = itunes.find_app_rank("pilates", 123456789, country="us") # → int | None
```

### PopularityEstimator

```python
estimator = PopularityEstimator()
score = estimator.estimate(competitors, "pilates")  # → int (5-100) | None
```

### DifficultyCalculator

```python
calculator = DifficultyCalculator()
score, breakdown = calculator.calculate(competitors, keyword="pilates")
# score: int (1-100)
# breakdown: dict with sub_scores, insights, opportunity_signals, ranking_tiers
```

### DownloadEstimator

```python
estimator = DownloadEstimator()
result = estimator.estimate(popularity=72, country="us")
# result["daily_searches"]: float
# result["positions"]: list of 20 dicts (pos, ttr, downloads_low, downloads_high)
# result["tiers"]: {"top_5": {low, high}, "top_6_10": {low, high}, "top_11_20": {low, high}}
```

### Helper Functions (module-level)

```python
from aso.services import _keyword_title_evidence, _is_brand_keyword

evidence = _keyword_title_evidence("pilates", "Pilates Workout App", "Health & Fitness")
# → {"exact_phrase": True, "all_words": True, "evidence": 1.0, ...}

is_brand, name = _is_brand_keyword("spotify", leader_app, all_competitors)
# → (True, "Spotify AB")
```
