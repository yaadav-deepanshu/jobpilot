"""
SQLite Job Database for JobPilot Mark 2
Tracks seen and emailed jobs to prevent duplicate email alerts across cron cycles
"""

import os
import sqlite3
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class JobDatabase:
    """Lightweight SQLite database for job tracking and deduplication"""

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Create tables if they don't exist"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    title TEXT NOT NULL,
                    company TEXT,
                    location TEXT,
                    platform TEXT,
                    date_posted TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    emailed BOOLEAN DEFAULT 0,
                    emailed_at TIMESTAMP,
                    search_count INTEGER DEFAULT 1,
                    min_amount REAL,
                    max_amount REAL,
                    currency TEXT,
                    num_applicants INTEGER,
                    description TEXT
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_seen_jobs_url ON seen_jobs(url);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_seen_jobs_emailed ON seen_jobs(emailed);")
            conn.commit()

    def is_job_emailed(self, url: str) -> bool:
        """Check if job has already been emailed"""
        if not url:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT emailed FROM seen_jobs WHERE url = ?", (url.strip(),))
            row = cursor.fetchone()
            return bool(row and row["emailed"])

    def filter_unemailed_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter a list of jobs, returning only those that haven't been emailed yet"""
        if not jobs:
            return []

        unemailed = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for j in jobs:
                url = (j.get("url") or "").strip()
                if not url:
                    continue
                cursor.execute("SELECT emailed FROM seen_jobs WHERE url = ?", (url,))
                row = cursor.fetchone()
                if not row or not row["emailed"]:
                    unemailed.append(j)
        return unemailed

    def record_jobs(self, jobs: List[Dict[str, Any]]) -> int:
        """Insert or update scraped jobs in the database"""
        if not jobs:
            return 0

        inserted_count = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for j in jobs:
                url = (j.get("url") or "").strip()
                if not url:
                    continue

                date_posted = j.get("date_posted")
                if hasattr(date_posted, "isoformat"):
                    date_posted = date_posted.isoformat()
                elif isinstance(date_posted, str):
                    pass
                else:
                    date_posted = None

                cursor.execute("SELECT id, search_count FROM seen_jobs WHERE url = ?", (url,))
                existing = cursor.fetchone()

                if existing:
                    cursor.execute(
                        "UPDATE seen_jobs SET search_count = search_count + 1 WHERE id = ?",
                        (existing["id"],)
                    )
                else:
                    cursor.execute("""
                        INSERT INTO seen_jobs (
                            url, title, company, location, platform, date_posted,
                            min_amount, max_amount, currency, num_applicants, description
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        url,
                        j.get("title", ""),
                        j.get("company", ""),
                        j.get("location", ""),
                        j.get("platform", ""),
                        date_posted,
                        j.get("min_amount"),
                        j.get("max_amount"),
                        j.get("currency"),
                        j.get("num_applicants"),
                        j.get("description", "")[:1000] if j.get("description") else ""
                    ))
                    inserted_count += 1
            conn.commit()
        return inserted_count

    def mark_jobs_as_emailed(self, job_urls: List[str]):
        """Mark given job URLs as sent in email"""
        if not job_urls:
            return

        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for url in job_urls:
                clean_url = (url or "").strip()
                if not clean_url:
                    continue
                cursor.execute(
                    "UPDATE seen_jobs SET emailed = 1, emailed_at = ? WHERE url = ?",
                    (now, clean_url)
                )
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        """Return total tracked and emailed stats"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS total FROM seen_jobs")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS emailed FROM seen_jobs WHERE emailed = 1")
            emailed = cursor.fetchone()["emailed"]

            cursor.execute("SELECT platform, COUNT(*) as count FROM seen_jobs GROUP BY platform")
            by_platform = {row["platform"]: row["count"] for row in cursor.fetchall() if row["platform"]}

        return {
            "total_seen": total,
            "total_emailed": emailed,
            "pending": total - emailed,
            "by_platform": by_platform
        }
