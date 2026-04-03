# RespectASO

<p align="center">
  <img src="desktop/assets/RespectASO.iconset/icon_256x256.png" alt="RespectASO" width="128">
</p>

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-Download_.dmg-purple?logo=apple&logoColor=white)](https://github.com/respectlytics/respectaso/releases/latest)
[![Version](https://img.shields.io/github/v/release/respectlytics/respectaso?color=purple&label=version)](https://github.com/respectlytics/respectaso/releases/latest)

**Free, open-source ASO keyword research tool for macOS. No API keys. No accounts. No data leaves your machine.**

RespectASO helps iOS developers research App Store keywords privately. Download the `.dmg`, drag to Applications, and get keyword popularity scores, difficulty analysis, competitor breakdowns, and download estimates — all without sending your research data to third-party services.

---

## Quick Start (Development)

```bash
# Install just (if not already installed)
brew install just

# Start the backend
just backend
```

This runs migrations and starts the Django dev server. Open the URL printed in the terminal to inspect the app.

## Why RespectASO?

Most ASO tools require paid subscriptions, API keys, and send your keyword research to their servers. RespectASO takes a different approach:

- **No API keys or credentials needed** — uses only the public iTunes Search API
- **Runs entirely on your machine** — all API calls originate from your local network
- **No telemetry, no analytics, no tracking** — zero data sent to any third party
- **Free and open-source** — AGPL-3.0 licensed, forever
- **Native Mac app** — download the `.dmg`, drag to Applications, done

## Features

| Feature | Description |
|---------|-------------|
| **Keyword Popularity** | Estimated popularity scores (1–100) derived from a 6-signal model analyzing iTunes Search competitor data |
| **Difficulty Score** | 7 weighted sub-scores (rating volume, dominant players, rating quality, market age, publisher diversity, app count, content relevance) with ranking tier analysis |
| **Ranking Tiers** | Separate difficulty analysis for Top 5, Top 10, and Top 20 positions |
| **Download Estimates** | Estimated daily downloads per ranking position based on search volume, tap-through rates, and conversion rates |
| **Competitor Analysis** | See the top 10 apps ranking for each keyword with ratings, reviews, genre, release date, and direct App Store links |
| **Country Opportunity Finder** | Scan up to 30 App Store regions at once to find which countries offer the best ranking opportunities |
| **Multi-Keyword Search** | Research up to 20 keywords at once (comma-separated) |
| **Multi-Country Search** | Search the same keyword across multiple countries simultaneously |
| **App Rank Tracking** | Add your apps and see where you rank for each keyword alongside competitor data |
| **Search History** | Browse past keyword research with sorting, filtering, and expandable detail views |
| **CSV Export** | Export your keyword research data for use in spreadsheets |
| **ASO Targeting Advice** | Automatic keyword classification (Sweet Spot, Hidden Gem, Low Volume, Avoid, etc.) |

## Download

**→ [Download RespectASO.dmg](https://github.com/respectlytics/respectaso/releases/latest)** (macOS 12+)

Open the `.dmg` and drag **RespectASO** into your **Applications** folder. Your data is stored at `~/Library/Application Support/RespectASO/` and survives app updates.

<details>
<summary><strong>Docker (legacy)</strong></summary>

```bash
git clone https://github.com/respectlytics/respectaso.git
cd respectaso
docker compose up -d
# Open http://localhost
```

</details>

## How Scoring Works

RespectASO uses the **iTunes Search API** as its only data source — no Apple Search Ads credentials, no scraping, no paid APIs.

### Popularity Score (1–100)

A 6-signal composite model that estimates how often a keyword is searched:

| Signal | Weight | What It Measures |
|--------|--------|------------------|
| Result count | 0–25 pts | How many apps appear for this keyword |
| Leader strength | 0–30 pts | Rating volume of the top-ranking apps |
| Title match density | 0–20 pts | How many apps use this exact keyword in their title |
| Market depth | 0–10 pts | Whether strong apps appear deep in results |
| Specificity penalty | -5 to -30 | Adjusts for generic terms that inflate result counts |
| Exact phrase bonus | 0–15 pts | Rewards multi-word keywords with precise matches |

### Difficulty Score (1–100)

A 7-factor weighted system that estimates how hard it is to rank:

| Factor | Weight | What It Measures |
|--------|--------|------------------|
| Rating volume | 30% | How many ratings competitors have |
| Dominant players | 20% | Whether a few apps dominate (100K+ ratings) |
| Rating quality | 10% | Average star ratings of competitors |
| Market maturity | 10% | How long competitors have been on the App Store |
| Publisher diversity | 10% | Whether results come from many publishers or a few |
| App count | 10% | Total number of relevant results |
| Content relevance | 10% | How well competitors match the keyword |

For the complete algorithm reference with every formula, calibration band, and interpolation method, see [docs/iOS_KEYWORD_VOLUME.md](docs/iOS_KEYWORD_VOLUME.md).

## Project Structure

```
aso/
  services.py       # Core engine: all scoring algorithms (2,068 lines)
  models.py          # Database models: App, Keyword, SearchResult
  views.py           # HTTP handlers (HTML pages + JSON API endpoints)
  scheduler.py       # Background auto-refresh daemon
  forms.py           # Django form validation
  templates/aso/     # Server-rendered UI (Django templates + Tailwind + vanilla JS)
  templatetags/      # Custom template filters
  migrations/        # Database schema evolution

core/                # Django project config (settings, urls, wsgi)
desktop/             # Native macOS app wrapper (pywebview + PyInstaller)
static/              # Favicons and logos
docs/                # Documentation
```

## Tech Stack

- **Python 3.12** + **Django 5.1** — backend + ORM
- **SQLite** — local single-user database
- **pywebview** — native macOS WebKit window
- **Tailwind CSS** (CDN) — dark theme UI (server-rendered, no JS framework)
- **iTunes Search API** — only external data source (public, no auth)

## Documentation

| Document | Description |
|----------|-------------|
| [iOS Keyword Volume & Algorithms](docs/iOS_KEYWORD_VOLUME.md) | Complete reference for all scoring algorithms, signals, weights, formulas, and external trend data sources |
| [Trend Signals Roadmap](docs/TREND_SIGNALS_ROADMAP.md) | Modular architecture for 17 external trend data sources with API docs, pricing, and implementation plans |
| [Headless Migration Guide](docs/HEADLESS_MIGRATION.md) | How to extract the core engine and integrate into a FastAPI + PostgreSQL project |
| [Security Policy](docs/SECURITY.md) | Vulnerability reporting and security design principles |
| [Contributing Guide](docs/CONTRIBUTING.md) | How to submit bug reports, feature requests, and pull requests |

## Privacy

RespectASO is designed with privacy as a core principle:

- **100% local** — the tool runs entirely on your machine
- **No accounts** — no registration, no login, no user tracking
- **No telemetry** — zero analytics, zero phone-home, zero data collection
- **No API keys** — uses only the public iTunes Search API
- **Your data stays yours** — keyword research never leaves your network

## License

[AGPL-3.0](LICENSE) — free to use, modify, and distribute. If you modify and deploy RespectASO as a service, you must share your changes under the same license.

## Contact

[respectlytics@loheden.com](mailto:respectlytics@loheden.com)

---

**Built by [Respectlytics](https://respectlytics.com/?utm_source=respectaso&utm_medium=readme&utm_campaign=oss)** — Privacy-focused mobile analytics for iOS & Android.
