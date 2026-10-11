"""
Comprehensive Automated Test Suite for JobPilot Mark 2
Tests:
- 30-minute recency window filtering
- Strict 0-4y experience cap and title exclusions
- <=100 applicant limit (numeric & text flags)
- Platform priority sorting (LinkedIn -> Indeed -> Naukri -> Rest)
- SQLite database deduplication and tracking
- HTML email template rendering & counts summary
- Mocked SMTP_SSL email dispatch
- End-to-end daemon execution cycle
"""

import os
import sys
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import pytest

# Ensure mark2 directory is in sys.path
mark2_dir = Path(__file__).resolve().parent.parent
if str(mark2_dir) not in sys.path:
    sys.path.insert(0, str(mark2_dir))

from db.database import JobDatabase
from filter.engine import Mark2FilterEngine
from notifier.email_sender import EmailNotifier
from main import JobPilotMark2Daemon

@pytest.fixture
def sample_config(tmp_path):
    db_file = str(tmp_path / "test_jobs.db")
    return {
        "profile": {
            "name": "Deepanshu Yadav",
            "email": "yaadav.deepanshu@gmail.com",
            "experience_years": 3,
            "target_experience_max": 4
        },
        "search": {
            "roles": [
                "Cloud Engineer",
                "DevOps Engineer",
                "Site Reliability Engineer",
                "SRE",
                "Platform Engineer"
            ],
            "location": "Bengaluru",
            "remote": True,
            "hybrid": True,
            "recency_minutes": 30,
            "max_applicants": 100,
            "min_experience_years": 0,
            "max_experience_years": 4,
            "exclude_keywords": ["internship", "volunteer", "unpaid", "part-time"]
        },
        "platforms": {
            "linkedin": {"enabled": True},
            "indeed": {"enabled": True},
            "naukri": {"enabled": True},
            "glassdoor": {"enabled": True},
            "zip_recruiter": {"enabled": True},
            "google": {"enabled": True},
            "bayt": {"enabled": True}
        },
        "email": {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 465,
            "sender_email": "test_sender@gmail.com",
            "sender_password": "test_app_password_16char",
            "recipient_email": "yaadav.deepanshu@gmail.com",
            "subject_prefix": "[JobPilot Mark 2]",
            "send_empty_digest": False
        },
        "scheduler": {
            "interval_minutes": 30
        },
        "database": {
            "path": db_file
        }
    }

class TestMark2FilterEngine:

    def test_30_minute_recency_filter(self, sample_config):
        engine = Mark2FilterEngine(sample_config)
        now = datetime.now(timezone.utc)

        jobs = [
            {
                "title": "Cloud Engineer",
                "company": "Company A",
                "location": "Bengaluru",
                "url": "https://example.com/job1",
                "date_posted": (now - timedelta(minutes=15)).isoformat(),
                "description": "AWS, Docker, Kubernetes"
            },
            {
                "title": "DevOps Engineer",
                "company": "Company B",
                "location": "Bengaluru",
                "url": "https://example.com/job2",
                "date_posted": (now - timedelta(minutes=50)).isoformat(), # Exceeds 30 mins
                "description": "CI/CD, Terraform, Python"
            }
        ]

        filtered = engine.filter_jobs(jobs, max_minutes=30)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Cloud Engineer"

    def test_strict_experience_cap_0_to_4_years(self, sample_config):
        engine = Mark2FilterEngine(sample_config)
        now = datetime.now(timezone.utc)

        jobs = [
            {
                "title": "Cloud Engineer",
                "company": "Company A",
                "location": "Bengaluru",
                "url": "https://example.com/job1",
                "date_posted": now.isoformat(),
                "description": "Requires 2-3 years of cloud engineering experience with AWS and Terraform."
            },
            {
                "title": "DevOps Engineer",
                "company": "Company B",
                "location": "Bengaluru",
                "url": "https://example.com/job2",
                "date_posted": now.isoformat(),
                "description": "Requires 6+ years of experience in SRE and DevOps operations." # Should be rejected
            },
            {
                "title": "Platform Engineer",
                "company": "Company C",
                "location": "Bengaluru",
                "url": "https://example.com/job3",
                "date_posted": now.isoformat(),
                "description": "Must have 5 to 8 years experience in Kubernetes and cloud infrastructure." # Should be rejected
            }
        ]

        filtered = engine.filter_jobs(jobs)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Cloud Engineer"

    def test_senior_title_exclusions(self, sample_config):
        engine = Mark2FilterEngine(sample_config)
        now = datetime.now(timezone.utc)

        jobs = [
            {"title": "Senior Cloud Engineer", "company": "A", "url": "https://1", "date_posted": now.isoformat(), "description": "AWS"},
            {"title": "Lead DevOps Engineer", "company": "B", "url": "https://2", "date_posted": now.isoformat(), "description": "AWS"},
            {"title": "Principal SRE", "company": "C", "url": "https://3", "date_posted": now.isoformat(), "description": "AWS"},
            {"title": "Engineering Manager", "company": "D", "url": "https://4", "date_posted": now.isoformat(), "description": "AWS"},
            {"title": "Staff Platform Engineer", "company": "E", "url": "https://5", "date_posted": now.isoformat(), "description": "AWS"},
            {"title": "DevOps Engineer", "company": "F", "url": "https://6", "date_posted": now.isoformat(), "description": "AWS, Docker, CI/CD"}
        ]

        filtered = engine.filter_jobs(jobs)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "DevOps Engineer"

    def test_applicant_threshold_max_100(self, sample_config):
        engine = Mark2FilterEngine(sample_config)
        now = datetime.now(timezone.utc)

        jobs = [
            {
                "title": "Cloud Engineer",
                "company": "A",
                "url": "https://1",
                "num_applicants": 45, # Passes
                "date_posted": now.isoformat(),
                "description": "AWS, Kubernetes"
            },
            {
                "title": "DevOps Engineer",
                "company": "B",
                "url": "https://2",
                "num_applicants": 140, # Exceeds 100
                "date_posted": now.isoformat(),
                "description": "AWS, Kubernetes"
            },
            {
                "title": "Site Reliability Engineer",
                "company": "C",
                "url": "https://3",
                "num_applicants": None,
                "date_posted": now.isoformat(),
                "description": "Over 100 people applied for this role on LinkedIn." # Text flag exceeds 100
            }
        ]

        filtered = engine.filter_jobs(jobs)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Cloud Engineer"

    def test_platform_priority_sorting(self, sample_config):
        engine = Mark2FilterEngine(sample_config)
        now = datetime.now(timezone.utc)

        jobs = [
            {"title": "DevOps Engineer", "company": "A", "platform": "naukri", "url": "https://n1", "date_posted": now.isoformat()},
            {"title": "SRE", "company": "B", "platform": "glassdoor", "url": "https://g1", "date_posted": now.isoformat()},
            {"title": "Cloud Engineer", "company": "C", "platform": "linkedin", "url": "https://l1", "date_posted": now.isoformat()},
            {"title": "Platform Engineer", "company": "D", "platform": "indeed", "url": "https://i1", "date_posted": now.isoformat()},
        ]

        sorted_jobs = engine._sort_by_platform_priority(jobs)
        platforms = [j["platform"] for j in sorted_jobs]
        assert platforms == ["linkedin", "indeed", "naukri", "glassdoor"]


class TestJobDatabase:

    def test_database_initialization_and_recording(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = JobDatabase(db_path=db_path)

        jobs = [
            {
                "title": "Cloud Engineer",
                "company": "Acme Corp",
                "location": "Bengaluru",
                "platform": "linkedin",
                "url": "https://linkedin.com/jobs/1",
                "num_applicants": 20,
                "description": "AWS Cloud"
            },
            {
                "title": "DevOps Engineer",
                "company": "Beta Inc",
                "location": "Remote",
                "platform": "indeed",
                "url": "https://indeed.com/jobs/2",
                "num_applicants": 35,
                "description": "Kubernetes CI/CD"
            }
        ]

        inserted = db.record_jobs(jobs)
        assert inserted == 2

        stats = db.get_stats()
        assert stats["total_seen"] == 2
        assert stats["total_emailed"] == 0
        assert stats["pending"] == 2
        assert stats["by_platform"]["linkedin"] == 1
        assert stats["by_platform"]["indeed"] == 1

    def test_database_unemailed_filtering_and_marking(self, tmp_path):
        db_path = str(tmp_path / "test2.db")
        db = JobDatabase(db_path=db_path)

        jobs = [
            {"title": "Job 1", "company": "A", "url": "https://job1", "platform": "linkedin"},
            {"title": "Job 2", "company": "B", "url": "https://job2", "platform": "indeed"},
        ]
        db.record_jobs(jobs)

        # Initially both are unemailed
        unemailed = db.filter_unemailed_jobs(jobs)
        assert len(unemailed) == 2

        # Mark Job 1 as emailed
        db.mark_jobs_as_emailed(["https://job1"])

        # Now only Job 2 should be returned
        unemailed_after = db.filter_unemailed_jobs(jobs)
        assert len(unemailed_after) == 1
        assert unemailed_after[0]["url"] == "https://job2"

        stats = db.get_stats()
        assert stats["total_emailed"] == 1
        assert stats["pending"] == 1


class TestEmailNotifier:

    def test_email_html_template_substitution(self, sample_config):
        notifier = EmailNotifier(config=sample_config)

        jobs = [
            {
                "title": "DevOps Engineer",
                "company": "Razorpay",
                "location": "Bengaluru",
                "platform": "linkedin",
                "url": "https://linkedin.com/jobs/razorpay",
                "num_applicants": 18,
                "description": "AWS, Docker, K8s"
            },
            {
                "title": "Cloud Engineer",
                "company": "Swiggy",
                "location": "Remote",
                "platform": "indeed",
                "url": "https://indeed.com/jobs/swiggy",
                "num_applicants": 42,
                "description": "Terraform, Linux"
            }
        ]

        html = notifier.build_email_content(jobs, window_minutes=30)
        assert "Deepanshu Yadav" in html
        assert "Last 30 Minutes" in html
        assert "Razorpay" in html
        assert "Swiggy" in html
        assert "LinkedIn:" in html
        assert "Indeed:" in html
        assert "Apply on LinkedIn" in html
        assert "Apply on Indeed" in html

    def test_is_configured_detection(self, sample_config):
        # With real-looking config
        notifier = EmailNotifier(config=sample_config)
        assert notifier.is_configured() is True

        # With placeholder config
        dummy_config = dict(sample_config)
        dummy_config["email"]["sender_email"] = "Your_Email@xyz.com"
        dummy_config["email"]["sender_password"] = "Enter_your_gmail_password"
        unconfigured_notifier = EmailNotifier(config=dummy_config)
        assert unconfigured_notifier.is_configured() is False

    @patch("smtplib.SMTP_SSL")
    def test_mocked_smtp_ssl_dispatch(self, mock_smtp_ssl, sample_config, tmp_path):
        preview_file = str(tmp_path / "test_preview.html")
        notifier = EmailNotifier(config=sample_config)

        mock_conn = MagicMock()
        mock_smtp_ssl.return_value = mock_conn

        jobs = [
            {
                "title": "SRE",
                "company": "CRED",
                "location": "Bengaluru",
                "platform": "linkedin",
                "url": "https://linkedin.com/jobs/cred",
                "num_applicants": 10
            }
        ]

        result = notifier.send_digest(jobs, window_minutes=30, save_preview_path=preview_file)
        assert result is True

        # Verify SMTP connection and calls
        mock_smtp_ssl.assert_called_once_with("smtp.gmail.com", 465, timeout=30)
        mock_conn.login.assert_called_once_with("test_sender@gmail.com", "test_app_password_16char")
        mock_conn.send_message.assert_called_once()
        mock_conn.close.assert_called_once()

        # Verify preview was written
        assert os.path.exists(preview_file)


class TestDaemonExecutionCycle:

    @patch("scraper.multi_platform.Mark2JobScraper.scrape_all")
    @patch("notifier.email_sender.EmailNotifier.send_digest")
    def test_daemon_cycle_execution(self, mock_send_digest, mock_scrape_all, sample_config):
        now = datetime.now(timezone.utc)
        mock_scrape_all.return_value = [
            {
                "title": "Cloud Engineer",
                "company": "Amazon",
                "location": "Bengaluru",
                "platform": "linkedin",
                "url": "https://amazon.jobs/1",
                "date_posted": now.isoformat(),
                "num_applicants": 30,
                "description": "AWS, Python, Linux"
            },
            {
                "title": "Senior Director",  # Excluded by filter
                "company": "BigCorp",
                "location": "Bengaluru",
                "platform": "indeed",
                "url": "https://indeed.com/2",
                "date_posted": now.isoformat(),
                "num_applicants": 10,
                "description": "Management"
            }
        ]
        mock_send_digest.return_value = True

        daemon = JobPilotMark2Daemon(config=sample_config)
        emailed_count = daemon.execute_cycle(minutes_old=30, dry_run=False)

        assert emailed_count == 1
        mock_scrape_all.assert_called_once_with(minutes_old=30)
        mock_send_digest.assert_called_once()

        # Verify DB recorded job as emailed
        stats = daemon.db.get_stats()
        assert stats["total_seen"] == 1
        assert stats["total_emailed"] == 1
        assert stats["pending"] == 0
