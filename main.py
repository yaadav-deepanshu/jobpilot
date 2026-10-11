"""
JobPilot Mark 2 - Headless Autonomous Job Finder & Email Alert Daemon
Runs every 30 minutes, filters 0-4y / <=100 applicants across LinkedIn, Indeed, Naukri,
and sends rich HTML email digests.
"""

import os
import sys
import yaml
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

from db.database import JobDatabase
from scraper.multi_platform import Mark2JobScraper
from filter.engine import Mark2FilterEngine
from notifier.email_sender import EmailNotifier

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

# Setup rich console logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join("data", "jobpilot_mark2.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger("JobPilotMark2")

def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration YAML"""
    path = Path(config_path)
    if not path.exists():
        logger.error(f"Config file not found at {config_path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

class JobPilotMark2Daemon:
    """Orchestrates scraping, filtering, database deduplication, and email dispatch"""

    def __init__(self, config: dict):
        self.config = config
        db_path = config.get("database", {}).get("path", "data/jobs.db")
        self.db = JobDatabase(db_path=db_path)
        self.scraper = Mark2JobScraper(config=config)
        self.filter_engine = Mark2FilterEngine(config=config)
        self.notifier = EmailNotifier(config=config)

        self.recency_minutes = config.get("search", {}).get("recency_minutes", 30)
        self.send_empty = config.get("email", {}).get("send_empty_digest", False)

    def execute_cycle(self, minutes_old: int = 30, dry_run: bool = False) -> int:
        """
        Execute one complete workflow cycle:
        1. Scrape raw jobs
        2. Filter strictly for 0-4y, <=100 applicants, and 30-min recency
        3. Save seen jobs to database
        4. Segregate never-before-emailed jobs
        5. Dispatch HTML email alert with counts and cards
        """
        logger.info("=" * 65)
        logger.info(f"🔄 Starting JobPilot Mark 2 Execution Cycle (Window: Last {minutes_old}m)")
        logger.info("=" * 65)

        # 1. Scrape
        try:
            raw_jobs = self.scraper.scrape_all(minutes_old=minutes_old)
        except Exception as e:
            logger.error(f"Scraper error during cycle: {e}")
            raw_jobs = []

        # 2. Filter
        qualified_jobs = self.filter_engine.filter_jobs(raw_jobs, max_minutes=minutes_old)
        logger.info(f"📊 Filter Evaluation: {len(raw_jobs)} raw → {len(qualified_jobs)} qualified jobs")

        # 3. Record in DB
        newly_inserted = self.db.record_jobs(qualified_jobs)
        logger.info(f"💾 Database update: {newly_inserted} new unique jobs recorded to SQLite")

        # 4. Find jobs not yet emailed
        unemailed_jobs = self.db.filter_unemailed_jobs(qualified_jobs)
        logger.info(f"📬 Unemailed opportunities in this window: {len(unemailed_jobs)}")

        # 5. Send Email if there are unemailed jobs (or configured to send empty digest)
        if not unemailed_jobs and not self.send_empty:
            logger.info("ℹ️ No new unemailed opportunities in this 30-minute window. Email skipped.")
            return 0

        # 6. Dispatch Email
        if dry_run:
            logger.info("🧪 Dry-run mode enabled: Generating HTML preview without sending SMTP email.")
            preview_file = "latest_email_preview.html"
            self.notifier.build_email_content(unemailed_jobs, window_minutes=minutes_old)
            self.notifier.send_digest(unemailed_jobs, window_minutes=minutes_old, save_preview_path=preview_file)
            return len(unemailed_jobs)

        email_sent = self.notifier.send_digest(unemailed_jobs, window_minutes=minutes_old)
        if email_sent:
            urls_to_mark = [j["url"] for j in unemailed_jobs if j.get("url")]
            self.db.mark_jobs_as_emailed(urls_to_mark)
            logger.info(f"✓ Marked {len(urls_to_mark)} jobs as emailed in database")
        else:
            logger.warning("⚠️ Email was not sent (check SMTP credentials in .env)")

        return len(unemailed_jobs)

def main():
    parser = argparse.ArgumentParser(description="JobPilot Mark 2 Daemon")
    parser.add_argument("--now", action="store_true", help="Run one scrape & email cycle immediately and exit")
    parser.add_argument("--dry-run", action="store_true", help="Run cycle and save HTML preview without sending email")
    parser.add_argument("--minutes", type=int, default=None, help="Override recency window in minutes (default: 30)")
    parser.add_argument("--interval", type=int, default=None, help="Override scheduler interval in minutes (default: 30)")
    parser.add_argument("--stats", action="store_true", help="Show database tracking statistics and exit")
    parser.add_argument("--test-email", action="store_true", help="Send a test email to verify credentials")

    args = parser.parse_args()
    config = load_config()

    daemon = JobPilotMark2Daemon(config=config)

    # Stats mode
    if args.stats:
        stats = daemon.db.get_stats()
        print("\n--- JobPilot Mark 2 Database Statistics ---")
        print(f"Total Seen Jobs:    {stats['total_seen']}")
        print(f"Total Emailed Jobs: {stats['total_emailed']}")
        print(f"Pending Unemailed:  {stats['pending']}")
        print(f"By Platform:        {stats['by_platform']}\n")
        sys.exit(0)

    # Test Email mode
    if args.test_email:
        print("\nTesting Email Dispatch...")
        dummy_jobs = [
            {
                "title": "Cloud Engineer (Test Alert)",
                "company": "Amazon Web Services",
                "location": "Bengaluru, India",
                "platform": "linkedin",
                "url": "https://www.linkedin.com/jobs",
                "num_applicants": 25,
                "description": "AWS, Docker, Kubernetes, Terraform test job."
            },
            {
                "title": "DevOps Engineer (Test Alert)",
                "company": "Razorpay",
                "location": "Bengaluru (Remote)",
                "platform": "indeed",
                "url": "https://www.indeed.com",
                "num_applicants": 12,
                "description": "CI/CD, Python, Linux, Prometheus test job."
            }
        ]
        success = daemon.notifier.send_digest(dummy_jobs, window_minutes=30)
        if success:
            print("✓ Test email sent successfully! Check your inbox.")
        else:
            print("✗ Failed to send test email. Please check .env configuration.")
        sys.exit(0 if success else 1)

    window = args.minutes if args.minutes is not None else daemon.recency_minutes

    # Immediate one-off run
    if args.now or args.dry_run:
        daemon.execute_cycle(minutes_old=window, dry_run=args.dry_run)
        sys.exit(0)

    # Scheduler loop (every 30 minutes)
    interval = args.interval or config.get("scheduler", {}).get("interval_minutes", 30)
    logger.info(f"⏰ Starting 30-minute scheduler daemon (Runs every {interval} mins)...")

    scheduler = BlockingScheduler()

    # Schedule recurring job every 30 minutes
    scheduler.add_job(
        daemon.execute_cycle,
        "interval",
        minutes=interval,
        args=[window, False],
        id="mark2_job_scrape"
    )

    # Run initial cycle immediately upon launch
    logger.info("🚀 Running initial startup cycle...")
    daemon.execute_cycle(minutes_old=window, dry_run=False)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 JobPilot Mark 2 daemon stopped.")

if __name__ == "__main__":
    main()
