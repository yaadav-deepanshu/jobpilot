"""
Multi-Platform Job Scraper for JobPilot Mark 2
Collects jobs across LinkedIn, Indeed, Naukri, Glassdoor, ZipRecruiter, Google, and Bayt via JobSpy
Supports 30-minute recency windowing and clean data normalization
"""

import logging
import math
import re
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from jobspy import scrape_jobs

logger = logging.getLogger(__name__)

class Mark2JobScraper:
    """Robust multi-platform job scraper using JobSpy with 30-minute windowing"""

    SUPPORTED_SITES = {
        'linkedin': {'site': 'linkedin', 'country': None},
        'indeed': {'site': 'indeed', 'country': 'india'},
        'naukri': {'site': 'naukri', 'country': None},
        'glassdoor': {'site': 'glassdoor', 'country': None},
        'zip_recruiter': {'site': 'zip_recruiter', 'country': None},
        'google': {'site': 'google', 'country': None},
        'bayt': {'site': 'bayt', 'country': None},
    }

    def __init__(self, config: dict):
        self.config = config
        self.search_config = config.get('search', {})
        self.roles = self.search_config.get('roles', ['Cloud Engineer', 'DevOps Engineer', 'SRE'])
        self.location = self.search_config.get('location', 'Bengaluru')
        self.recency_minutes = self.search_config.get('recency_minutes', 30)

    def scrape_all(
        self,
        minutes_old: Optional[int] = None,
        results_per_query: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Scrape jobs across enabled platforms.
        minutes_old: Recency window in minutes (default 30).
        """
        all_jobs = []
        enabled_platforms = self._get_enabled_platforms()
        window_minutes = minutes_old if minutes_old is not None else self.recency_minutes

        # Calculate hours_old for JobSpy (e.g. 30 mins -> 0.5 or 1 hour conservative query)
        hours_for_jobspy = max(round(window_minutes / 60.0, 1), 0.5)

        logger.info(f"🚀 Starting 30-minute scrape across {len(enabled_platforms)} platforms (window: {window_minutes}m, hours: {hours_for_jobspy}h)")

        # Query top roles to balance depth and request speed
        search_roles = self.roles[:4]

        for platform_key, site_info in enabled_platforms.items():
            site_name = site_info['site']
            country = site_info['country']

            for role in search_roles:
                logger.info(f"Fetching {platform_key.capitalize()} for '{role}' in {self.location}...")

                try:
                    kwargs = {
                        'site_name': [site_name],
                        'search_term': role,
                        'location': self.location,
                        'results_wanted': results_per_query,
                        'fetch_description': True,
                        'hours_old': hours_for_jobspy,
                    }

                    if country:
                        kwargs['country_indeed'] = country

                    df = scrape_jobs(**kwargs)

                    if df is not None and len(df) > 0:
                        records = df.to_dict('records')
                        formatted = self._format_records(records, platform_key)
                        all_jobs.extend(formatted)
                        logger.info(f"  ✓ {platform_key}: Found {len(formatted)} raw jobs for '{role}'")
                    else:
                        logger.info(f"  - {platform_key}: No jobs returned for '{role}'")

                except Exception as e:
                    logger.warning(f"  ✗ {platform_key} scrape error for '{role}': {e}")

        logger.info(f"✓ Raw scrape complete: Found {len(all_jobs)} total raw jobs before filtering")
        return all_jobs

    def _get_enabled_platforms(self) -> Dict[str, Dict]:
        platforms_config = self.config.get('platforms', {})
        enabled = {}
        for key, info in self.SUPPORTED_SITES.items():
            if platforms_config.get(key, {}).get('enabled', True):
                enabled[key] = info
        return enabled

    def _format_records(self, records: List[Dict], platform: str) -> List[Dict]:
        formatted = []
        for r in records:
            # Handle pandas NaN safely
            def _clean_str(val, default=''):
                if val is None:
                    return default
                if isinstance(val, float) and math.isnan(val):
                    return default
                s = str(val).strip()
                return s if s != 'nan' else default

            def _clean_int(val, default=None):
                if val is None:
                    return default
                if isinstance(val, float) and math.isnan(val):
                    return default
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return default

            def _clean_float(val, default=None):
                if val is None:
                    return default
                if isinstance(val, float) and math.isnan(val):
                    return default
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            job_url = _clean_str(r.get('job_url'))
            if not job_url:
                continue

            num_apps = _clean_int(r.get('num_applicants'))
            desc = _clean_str(r.get('description'))

            # Extract textual applicant indicators if numeric is absent
            if num_apps is None and desc:
                desc_lower = desc.lower()
                if any(x in desc_lower for x in ['over 100 people applied', 'over 100 applicants', '100+ applicants', 'over 100 people clicked apply']):
                    num_apps = 101
                else:
                    m = re.search(r'(\d+)\s*(?:\+|plus)?\s*(?:applicants|people\s+applied|people\s+clicked\s+apply)', desc_lower)
                    if m:
                        try:
                            num_apps = int(m.group(1))
                        except (ValueError, TypeError):
                            pass

            date_posted = r.get('date_posted')
            if date_posted is not None and isinstance(date_posted, float) and math.isnan(date_posted):
                date_posted = None

            formatted.append({
                'title': _clean_str(r.get('title')),
                'company': _clean_str(r.get('company')),
                'location': _clean_str(r.get('location'), self.location),
                'platform': platform,
                'url': job_url,
                'description': desc,
                'date_posted': date_posted,
                'job_type': _clean_str(r.get('job_type')),
                'min_amount': _clean_float(r.get('min_amount')),
                'max_amount': _clean_float(r.get('max_amount')),
                'currency': _clean_str(r.get('currency')),
                'num_applicants': num_apps,
            })
        return formatted
