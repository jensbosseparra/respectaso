"""
Base class for all trend signal collectors.

Each collector is a self-contained module that:
1. Fetches data from one external source
2. Normalises it into TrendSignal rows
3. Persists via Django ORM (upsert by unique constraint)
"""

from __future__ import annotations

import abc
import logging
from datetime import date, datetime, timezone as tz

from aso.models import TrendSignal

logger = logging.getLogger(__name__)


class BaseSignalCollector(abc.ABC):
    """Abstract base for every signal source."""

    source_id: str  # e.g. "google_trends" — must match TrendSignal.SOURCE_CHOICES

    @abc.abstractmethod
    def collect(self, keywords: list[str], country: str = "us") -> list[dict]:
        """
        Fetch trend data and return a list of dicts, each with at least:
            keyword, raw_volume, normalized_score, country, metadata
        """

    # ------------------------------------------------------------------
    # Shared persistence — subclasses call self.save_signals(rows)
    # ------------------------------------------------------------------

    def save_signals(self, rows: list[dict]) -> int:
        """
        Upsert rows into TrendSignal.  Returns count of rows saved.
        Uses update_or_create keyed on (source, keyword, country, date_stamp).
        """
        saved = 0
        now = datetime.now(tz.utc)
        today = date.today()

        for row in rows:
            keyword = row["keyword"].lower().strip()
            country = row.get("country", "us").lower()
            defaults = {
                "raw_volume": row.get("raw_volume"),
                "normalized_score": row.get("normalized_score"),
                "metadata": row.get("metadata", {}),
                "collected_at": now,
            }

            obj, created = TrendSignal.objects.update_or_create(
                source=self.source_id,
                keyword=keyword,
                country=country,
                date_stamp=row.get("date_stamp", today),
                defaults=defaults,
            )
            # first_seen_at is handled by TrendSignal.save() override
            saved += 1

        logger.info("[%s] saved %d signal(s)", self.source_id, saved)
        return saved
