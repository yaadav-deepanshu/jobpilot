# 🚀 JobPilot Mark 2 — Autonomous 30-Minute Job Alert Daemon

**JobPilot Mark 2** is a headless, autonomous background daemon designed to scrape, filter, and dispatch real-time job opportunities directly to your email every 30 minutes.

Unlike Mark 1 (which includes an interactive Flask web UI), **Mark 2** is lightweight, runs without any UI dependencies, stores discovered jobs in a local SQLite database to prevent duplicate alerts, and dispatches rich HTML email digests.

---

## 🎯 Candidate Profile & Strict Filtering Rules
* **Candidate:** Deepanshu Yadav (`yaadav.deepanshu@gmail.com`)
* **Experience Level:** 3 years in Cloud / DevOps / SRE engineering.
* **Target Roles:** Cloud Engineer, DevOps Engineer, Site Reliability Engineer (SRE), Platform Engineer, Systems Engineer.
* **Recency Threshold:** **Strict 30-Minute Window** (`recency_minutes: 30`).
* **Experience Cap:** **Strict 0 to 4 Years** (Hard exclusion of 5+, 6+, 7+, 8+, 10+, 5–8y, 6–9y).
* **Senior Title Exclusions:** Auto-excludes `Senior`, `Sr.`, `Lead`, `Principal`, `Staff`, `Architect`, `Director`, `Manager`, `Head of`, `VP`, `AVP`.
* **Applicant Cap:** Strictly **≤ 100 applicants** (excludes >100 applicants numerically or text flags like *"over 100 people clicked apply"*).
* **Platform Priority Display:** **LinkedIn (1) → Indeed (2) → Naukri (3) → Rest (4)**.

---

## 📁 Project Architecture

```
G:\Geonix\vscode\ai\jobpilot-mark2\
├── config.yaml               # Candidate profile, 30m window, platform switches, email config
├── .env.example              # Example environment secrets (Gmail App Password)
├── .env                      # Active local secrets file
├── main.py                   # Main daemon entrypoint (scheduler, --now, --dry-run, --stats)
├── requirements.txt          # Python dependencies (JobSpy, pandas, APScheduler, pytest, etc.)
├── Dockerfile                # Docker container definition (Python 3.12-slim)
├── docker-compose.yml        # Docker Compose configuration with persistent SQLite volume
├── .dockerignore             # Docker build exclusions
├── db/
│   └── database.py           # SQLite tracking database (prevents duplicate emails)
├── scraper/
│   └── multi_platform.py     # Multi-platform scraper (JobSpy: LinkedIn, Indeed, Naukri, etc.)
├── filter/
│   └── engine.py             # 30-min recency, 0-4y cap, <=100 applicant filter, platform sort
├── notifier/
│   └── email_sender.py       # Gmail SMTP_SSL HTML email sender
├── templates/
│   └── email_template.html   # Rich, mobile-responsive HTML email template
├── tests/
│   └── test_mark2.py         # 11 automated test cases (100% pass rate)
└── data/
    └── jobs.db               # SQLite database file storing seen & emailed records
```

---

## ⚙️ Configuration & Gmail Setup

### 1. Configure Email Credentials in `.env`
Mark 2 uses **Gmail SMTP over SSL (Port 465)**. To allow automated sending:
1. Go to your **[Google Account Security](https://myaccount.google.com/security)** and verify **2-Step Verification** is turned ON.
2. Go to **[App Passwords](https://myaccount.google.com/apppasswords)**.
3. Create a new app name (e.g. `JobPilot Mark 2`) and copy the generated **16-character password**.
4. Open `.env` and fill in your details:

```env
GMAIL_USER=Your_Email@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
RECIPIENT_EMAIL=yaadav.deepanshu@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
```

---

## 🚀 Running the Project

### Option A: Local Python Daemon

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Test your email configuration:**
   ```bash
   python main.py --test-email
   ```

3. **Run a single scrape cycle immediately (Dry-run without sending email):**
   ```bash
   python main.py --dry-run
   ```
   *(This generates `latest_email_preview.html` on disk so you can review the visual email in your browser!)*

4. **Run a single scrape cycle and dispatch real email:**
   ```bash
   python main.py --now
   ```

5. **Start the 30-minute automated scheduler:**
   ```bash
   python main.py
   ```
   *(Executes immediately upon startup, then automatically repeats every 30 minutes).*

6. **View SQLite tracking statistics:**
   ```bash
   python main.py --stats
   ```

---

### Option B: Docker / Docker Compose

1. **Build and start the container in the background:**
   ```bash
   docker compose up -d --build
   ```

2. **View live logs:**
   ```bash
   docker compose logs -f
   ```

3. **Stop the daemon:**
   ```bash
   docker compose down
   ```

*(The SQLite database is mounted into `./data/jobs.db` on your host machine, so your history and deduplication survive container rebuilds).*

---

## 🧪 Automated Testing
Run the comprehensive test suite (covers 30-minute recency filtering, 0-4y experience cap, applicant parsing, platform sorting, database deduplication, and mocked SMTP SSL dispatch):

```bash
pytest tests/test_mark2.py -v
```
*(All 11 tests pass with 100% pass rate).*
