"""
Django management command to run trend signal collectors.

Usage:
    # Fetch Google Trends RSS (free, no auth):
    python manage.py collect_trends google_trends --backend rss --country us

    # Fetch interest-over-time for specific keywords (free, needs pytrends-modern):
    python manage.py collect_trends google_trends --backend pytrends --keywords "pilates,yoga app,meditation"

    # Use SerpAPI (paid, needs SERPAPI_API_KEY):
    python manage.py collect_trends google_trends --backend serpapi --keywords "pilates" --country us

    # List available collectors:
    python manage.py collect_trends --list
"""

from django.core.management.base import BaseCommand

# Import the google_trends sub-package so it registers itself
import aso.signals.google_trends  # noqa: F401
from aso.signals import available_collectors, get_collector


class Command(BaseCommand):
    help = "Run a trend signal collector to fetch and store external trend data."

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            nargs="?",
            help="Collector name (e.g. google_trends). Use --list to see all.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all available collectors and exit.",
        )
        parser.add_argument(
            "--backend",
            default="rss",
            choices=["rss", "pytrends", "serpapi"],
            help="Backend to use (default: rss).",
        )
        parser.add_argument(
            "--keywords",
            default="",
            help="Comma-separated keywords (only for pytrends/serpapi backends).",
        )
        parser.add_argument(
            "--country",
            default="us",
            help="Country code (default: us).",
        )
        parser.add_argument(
            "--api-key",
            default="",
            help="API key (for serpapi backend). Falls back to SERPAPI_API_KEY env var.",
        )

    def handle(self, *args, **options):
        if options["list"]:
            collectors = available_collectors()
            if not collectors:
                self.stdout.write("No collectors registered.")
            else:
                self.stdout.write("Available collectors:")
                for name in collectors:
                    self.stdout.write(f"  - {name}")
            return

        source = options["source"]
        if not source:
            self.stderr.write("Error: provide a source name or use --list.\n")
            return

        try:
            cls = get_collector(source)
        except KeyError:
            self.stderr.write(
                f"Unknown collector: {source!r}. Use --list to see available.\n"
            )
            return

        backend = options["backend"]
        keywords = [k.strip() for k in options["keywords"].split(",") if k.strip()]
        country = options["country"].lower()
        api_key = options["api_key"]

        kwargs = {"backend": backend}
        if api_key:
            kwargs["api_key"] = api_key

        collector = cls(**kwargs)

        self.stdout.write(
            f"Collecting [{source}] via {backend} backend "
            f"(country={country}, keywords={keywords or 'trending'})..."
        )

        try:
            rows = collector.collect(keywords=keywords, country=country)
            saved = collector.save_signals(rows)
            self.stdout.write(self.style.SUCCESS(
                f"Done — {saved} signal(s) saved to TrendSignal table."
            ))

            # Show a preview of what was collected
            if rows:
                self.stdout.write("\nTop 10 signals:")
                for row in rows[:10]:
                    score = row.get("normalized_score")
                    score_str = f"{score:.2f}" if score is not None else "n/a"
                    method = row.get("metadata", {}).get("method", "?")
                    self.stdout.write(
                        f"  [{method}] {row['keyword']:<40} "
                        f"score={score_str}  raw={row.get('raw_volume')}"
                    )
        except ImportError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Collection failed: {exc}"))
