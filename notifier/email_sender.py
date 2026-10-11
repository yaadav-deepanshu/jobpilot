"""
Email Notifier for JobPilot Mark 2
Uses standard library EmailMessage and smtplib.SMTP_SSL to dispatch
rich HTML digests with platform breakdown and job opportunities.
"""

import os
import logging
import smtplib as smtp
from email.message import EmailMessage
from pathlib import Path
from string import Template
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PLATFORM_DISPLAY = {
    'linkedin': 'LinkedIn',
    'indeed': 'Indeed',
    'naukri': 'Naukri',
    'glassdoor': 'Glassdoor',
    'zip_recruiter': 'ZipRecruiter',
    'google': 'Google Jobs',
    'bayt': 'Bayt'
}

PLACEHOLDERS = {
    'your_email@xyz.com', 'your_email@gmail.com', 'enter_your_gmail_password',
    'enter_your_16_char_app_password', '${gmail_user}', '${gmail_app_password}',
    '${recipient_email}', 'email@xyz.com'
}

class EmailNotifier:
    """Dispatches HTML job digest alerts via Gmail SMTP SSL"""

    def __init__(self, config: dict, template_path: Optional[str] = None):
        load_dotenv()
        self.config = config
        self.email_config = config.get('email', {})
        self.profile = config.get('profile', {})

        def _resolve_val(env_key: str, cfg_key: str, default: str = '') -> str:
            val = (os.getenv(env_key) or '').strip()
            if not val or val.lower() in PLACEHOLDERS:
                val = (self.email_config.get(cfg_key) or '').strip()
            if val.lower() in PLACEHOLDERS:
                val = default
            return val

        self.email_addr = _resolve_val('GMAIL_USER', 'sender_email')
        self.email_passwd = _resolve_val('GMAIL_APP_PASSWORD', 'sender_password')
        self.recipient_email = _resolve_val(
            'RECIPIENT_EMAIL', 'recipient_email', default=self.profile.get('email', '')
        )

        self.smtp_host = os.getenv('SMTP_HOST') or self.email_config.get('smtp_host', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT') or self.email_config.get('smtp_port', 465))
        self.subject_prefix = self.email_config.get('subject_prefix', '[JobPilot Alert]')

        # Resolve template path
        if template_path:
            self.template_path = Path(template_path)
        else:
            base_dir = Path(__file__).resolve().parent.parent
            self.template_path = base_dir / "templates" / "email_template.html"

    def is_configured(self) -> bool:
        """Check if real credentials have been provided (not placeholder strings)"""
        if not self.email_addr or not self.email_passwd or not self.recipient_email:
            return False

        if self.email_addr.lower() in PLACEHOLDERS or self.email_passwd.lower() in PLACEHOLDERS:
            return False

        return True

    def build_email_content(self, jobs: List[Dict[str, Any]], window_minutes: int = 30) -> str:
        """Render email HTML using Template substitution matching user pattern"""
        template_text = self.template_path.read_text(encoding='utf-8')
        html_template = Template(template_text)

        total_count = len(jobs)
        candidate_name = self.profile.get('name', 'Deepanshu Yadav')

        # 1. Platform counts breakdown
        platform_counts = {}
        for j in jobs:
            plat = (j.get('platform') or 'other').lower()
            platform_counts[plat] = platform_counts.get(plat, 0) + 1

        # Priority display: linkedin, indeed, naukri, glassdoor, etc.
        priority_keys = ['linkedin', 'indeed', 'naukri', 'glassdoor', 'zip_recruiter', 'google', 'bayt']
        plat_parts = []
        for pk in priority_keys:
            if pk in platform_counts:
                display_name = PLATFORM_DISPLAY.get(pk, pk.capitalize())
                plat_parts.append(f"<strong>{display_name}:</strong> {platform_counts[pk]}")
        for k, v in platform_counts.items():
            if k not in priority_keys:
                display_name = PLATFORM_DISPLAY.get(k, k.capitalize())
                plat_parts.append(f"<strong>{display_name}:</strong> {v}")
        platform_breakdown = " • ".join(plat_parts) if plat_parts else "None"

        # 2. Location breakdown
        loc_bengaluru = 0
        loc_remote = 0
        for j in jobs:
            text = f"{(j.get('location') or '').lower()} {(j.get('title') or '').lower()}"
            if 'bengaluru' in text or 'bangalore' in text:
                loc_bengaluru += 1
            if 'remote' in text or 'wfh' in text:
                loc_remote += 1
        location_breakdown = f"<strong>Bengaluru:</strong> {loc_bengaluru} • <strong>Remote:</strong> {loc_remote}"

        # 3. Build job cards HTML
        cards_html = []
        for idx, j in enumerate(jobs, start=1):
            title = j.get('title', 'Unknown Role')
            company = j.get('company', 'Unknown Company')
            location = j.get('location', 'Bengaluru, India')
            platform = (j.get('platform') or 'job').lower()
            url = j.get('url', '#')
            num_apps = j.get('num_applicants')

            apps_badge = f'<span class="badge badge-info">{num_apps} Applicants</span>' if num_apps is not None else '<span class="badge badge-info">&le; 100 Applicants</span>'
            badge_class = f"badge-{platform}" if platform in ['linkedin', 'indeed', 'naukri', 'glassdoor', 'zip_recruiter', 'google', 'bayt'] else "badge-other"
            display_plat = PLATFORM_DISPLAY.get(platform, platform.capitalize())

            card = f"""
            <div class="job-card">
              <div class="job-card-header">
                <span class="badge {badge_class}">#{idx} {platform.upper()}</span>
                {apps_badge}
                <span class="badge badge-info">0-4y Match</span>
              </div>
              <div class="job-title">{title}</div>
              <div class="job-meta">
                <span class="job-company">🏢 {company}</span> &nbsp;•&nbsp;
                <span class="job-location">📍 {location}</span>
              </div>
              <div>
                <a href="{url}" target="_blank" class="btn-apply">Apply on {display_plat} &rarr;</a>
              </div>
            </div>
            """
            cards_html.append(card)

        if not cards_html:
            jobs_cards_str = """
            <div class="job-card" style="text-align: center; color: #94a3b8; padding: 28px;">
              No fresh jobs matched the strict 0-4y / ≤100 applicants criteria in the last 30 minutes.
            </div>
            """
        else:
            jobs_cards_str = "\n".join(cards_html)

        # Indian Standard Time (IST) timestamp
        ist_now = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%d %b %Y, %I:%M %p")

        substituted_html = html_template.substitute({
            "name": candidate_name,
            "window_minutes": str(window_minutes),
            "total_jobs": str(total_count),
            "platform_breakdown": platform_breakdown,
            "location_breakdown": location_breakdown,
            "jobs_cards_html": jobs_cards_str,
            "timestamp": ist_now
        })

        return substituted_html

    def send_digest(
        self,
        jobs: List[Dict[str, Any]],
        window_minutes: int = 30,
        save_preview_path: Optional[str] = "latest_email_preview.html"
    ) -> bool:
        """
        Builds and sends the digest email using the user's smtplib.SMTP_SSL pattern.
        Saves a local preview HTML file if credentials are not yet configured.
        """
        rendered_html = self.build_email_content(jobs, window_minutes=window_minutes)

        # Always save latest HTML preview locally so user can inspect it
        if save_preview_path:
            try:
                Path(save_preview_path).write_text(rendered_html, encoding='utf-8')
                logger.info(f"💾 Saved latest email preview to {save_preview_path}")
            except Exception as e:
                logger.warning(f"Could not save email preview: {e}")

        if not self.is_configured():
            logger.warning(
                "⚠️ Gmail SMTP credentials not configured in .env or config.yaml! "
                "Email skipped. Open 'latest_email_preview.html' in your browser to view the rendered digest."
            )
            return False

        subject = f"{self.subject_prefix} {len(jobs)} Fresh Opportunities (Last {window_minutes}m)"

        try:
            email = EmailMessage()
            email['From'] = self.email_addr
            email['To'] = self.recipient_email
            email['Subject'] = subject
            email.set_content(rendered_html, subtype='html')

            logger.info(f"📨 Connecting to {self.smtp_host}:{self.smtp_port} via SSL...")
            connection = smtp.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)
            connection.login(self.email_addr, self.email_passwd)
            connection.send_message(email)
            connection.close()

            logger.info(f"✓ Email successfully sent to {self.recipient_email} with {len(jobs)} jobs!")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to send email via SMTP_SSL: {e}")
            return False
