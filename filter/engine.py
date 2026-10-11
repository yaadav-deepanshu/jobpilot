"""
Smart Job Filter Engine for JobPilot Mark 2
Enforces 30-minute recency window, 0-4y strict experience cap, <=100 applicant limit,
and LinkedIn -> Indeed -> Naukri -> Rest platform priority sorting.
"""

import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class Mark2FilterEngine:
    """Intelligent job filter matching target profile with 30-minute recency"""

    ROLE_SYNONYMS = {
        'sre': ['site reliability engineer', 'site reliability', 'reliability engineer', 'sre'],
        'site reliability engineer': ['sre', 'site reliability', 'reliability engineer'],
        'devops': ['devops engineer', 'devops', 'cloud devops', 'devsecops'],
        'devops engineer': ['devops', 'cloud devops', 'devsecops', 'site reliability engineer', 'platform engineer'],
        'cloud engineer': ['cloud', 'aws engineer', 'azure engineer', 'gcp engineer', 'cloud infrastructure', 'cloud specialist'],
        'platform engineer': ['platform', 'infrastructure engineer', 'systems engineer', 'devops'],
        'infrastructure engineer': ['infrastructure', 'cloud infrastructure', 'iac', 'systems engineer'],
    }

    CORE_SKILLS = [
        'aws', 'azure', 'gcp', 'cloud', 'docker', 'kubernetes', 'k8s',
        'terraform', 'ansible', 'jenkins', 'ci/cd', 'python', 'linux',
        'bash', 'git', 'helm', 'prometheus', 'grafana', 'devops', 'sre'
    ]

    def __init__(self, config: dict):
        self.config = config
        self.search_config = config.get('search', {})
        self.target_roles = [r.lower() for r in self.search_config.get('roles', [])]
        self.target_location = self.search_config.get('location', '').lower()
        self.max_applicants = self.search_config.get('max_applicants', 100)
        self.max_exp_years = self.search_config.get('max_experience_years', 4)
        self.recency_minutes = self.search_config.get('recency_minutes', 30)
        self.exclude_keywords = [k.lower() for k in self.search_config.get('exclude_keywords', [])]

    def filter_jobs(
        self,
        jobs: List[Dict[str, Any]],
        max_minutes: Optional[int] = None,
        location_mode: str = 'both'
    ) -> List[Dict[str, Any]]:
        """Filter jobs through 30-min recency, experience, keywords, applicants, and platform priority"""
        initial_count = len(jobs)
        effective_minutes = max_minutes if max_minutes is not None else self.recency_minutes

        logger.info(f"🔎 Filtering {initial_count} jobs (window: {effective_minutes}m, loc: {location_mode})...")

        # 1. 30-Minute Recency Filter
        filtered = self._filter_by_recency(jobs, max_minutes=effective_minutes)

        # 2. Exclude negative keywords (internship, unpaid, etc.)
        filtered = self._filter_by_excluded_keywords(filtered)

        # 3. Experience filter (0-4 years strictly, exclude senior/lead/manager)
        filtered = self._filter_by_experience(filtered)

        # 4. Role and skill matching
        filtered = self._filter_by_role_and_skills(filtered)

        # 5. Location matching
        filtered = self._filter_by_location(filtered, location_mode=location_mode)

        # 6. Applicant threshold (<= 100 applicants)
        filtered = self._filter_by_applicants(filtered)

        # 7. Deduplication
        filtered = self._deduplicate(filtered)

        # 8. Sort by platform priority: LinkedIn (1) -> Indeed (2) -> Naukri (3) -> Rest (4)
        filtered = self._sort_by_platform_priority(filtered)

        logger.info(f"✓ Filter complete: {initial_count} raw → {len(filtered)} qualified jobs")
        return filtered

    def _filter_by_recency(self, jobs: List[Dict], max_minutes: int = 30) -> List[Dict]:
        """Keep jobs posted within max_minutes (e.g. 30 minutes)"""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=max_minutes)
        passed = []

        for j in jobs:
            posted = j.get('date_posted')
            if not posted:
                passed.append(j)
                continue

            try:
                if isinstance(posted, str):
                    posted = datetime.fromisoformat(posted.replace('Z', '+00:00'))
                if hasattr(posted, 'tzinfo') and posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                if posted >= cutoff:
                    passed.append(j)
            except Exception:
                passed.append(j)

        return passed

    def _filter_by_excluded_keywords(self, jobs: List[Dict]) -> List[Dict]:
        """Exclude jobs containing forbidden keywords"""
        if not self.exclude_keywords:
            return jobs

        passed = []
        for j in jobs:
            title = (j.get('title') or '').lower()
            desc = (j.get('description') or '').lower()[:300]
            text = f"{title} {desc}"
            if not any(k in text for k in self.exclude_keywords):
                passed.append(j)
        return passed

    def _filter_by_experience(self, jobs: List[Dict]) -> List[Dict]:
        """Strictly exclude roles requiring > 4 years experience or senior/lead/manager titles"""
        senior_titles = [
            'senior', 'sr.', 'sr ', 'sr/', 'lead', 'principal', 'staff',
            'architect', 'director', 'manager', 'head of', 'vp', 'vice president'
        ]

        excessive_phrases = [
            '5+ years', '6+ years', '7+ years', '8+ years', '9+ years', '10+ years',
            '5+ yrs', '6+ yrs', '7+ yrs', '8+ yrs', '9+ yrs', '10+ yrs',
            '5 years of experience', '6 years of experience', '7 years of experience',
            '8 years of experience', '10 years of experience',
            '5-8 years', '6-9 years', '5-9 years', '5-7 years', '6-8 years', '7-10 years', '8-10 years',
            'expert level', 'senior level'
        ]

        passed = []
        for j in jobs:
            title = (j.get('title') or '').lower()
            desc = (j.get('description') or '').lower()

            # Reject senior/lead titles
            if any(st in title for st in senior_titles):
                continue

            # Reject excessive phrases in description
            if any(phrase in desc for phrase in excessive_phrases):
                continue

            too_senior = False

            # Pattern 1: e.g. "5+ years of experience", "5-7 years"
            matches = re.findall(r'(\d+)\s*(?:\+|plus)?\s*(?:-|to)?\s*(\d+)?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)', desc)
            for m in matches:
                try:
                    min_req = int(m[0])
                    if min_req > self.max_exp_years:
                        too_senior = True
                        break
                    if m[1] and int(m[1]) > self.max_exp_years + 1:
                        too_senior = True
                        break
                except (ValueError, TypeError):
                    pass

            # Pattern 2: e.g. "minimum 5 years"
            if not too_senior:
                min_matches = re.findall(r'(?:minimum|at\s+least|min\.?)\s+(\d+)\s*(?:\+|plus)?\s*(?:years?|yrs?)', desc)
                for am in min_matches:
                    try:
                        if int(am) > self.max_exp_years:
                            too_senior = True
                            break
                    except (ValueError, TypeError):
                        pass

            if not too_senior:
                passed.append(j)

        return passed

    def _filter_by_role_and_skills(self, jobs: List[Dict]) -> List[Dict]:
        """Match if title matches target role or description contains 3+ cloud/DevOps skills"""
        if not self.target_roles:
            return jobs

        all_terms = set(self.target_roles)
        for r in self.target_roles:
            for syn in self.ROLE_SYNONYMS.get(r, []):
                all_terms.add(syn.lower())

        passed = []
        for j in jobs:
            title = (j.get('title') or '').lower()
            desc = (j.get('description') or '').lower()

            if any(term in title for term in all_terms):
                passed.append(j)
                continue

            if any(w in title for w in ['engineer', 'developer', 'specialist', 'analyst']):
                skill_count = sum(1 for s in self.CORE_SKILLS if s in desc)
                if skill_count >= 3:
                    passed.append(j)

        return passed

    def _filter_by_location(self, jobs: List[Dict], location_mode: str = 'both') -> List[Dict]:
        """Match preferred location (Bengaluru / Remote / Both)"""
        mode = (location_mode or 'both').lower().strip()

        if mode == 'remote':
            return [
                j for j in jobs
                if any(w in f"{(j.get('location') or '').lower()} {(j.get('title') or '').lower()} {(j.get('description') or '').lower()}"
                       for w in ['remote', 'work from home', 'wfh'])
            ]

        if mode == 'bengaluru':
            return [
                j for j in jobs
                if 'bengaluru' in (j.get('location') or '').lower() or 'bangalore' in (j.get('location') or '').lower()
            ]

        # 'both' mode: allow Bengaluru, Bangalore, Remote, Hybrid, or unspecified
        passed = []
        for j in jobs:
            loc = (j.get('location') or '').lower()
            if any(k in loc for k in ['bengaluru', 'bangalore', 'india', 'all']):
                passed.append(j)
            elif any(w in loc for w in ['remote', 'hybrid', 'wfh']):
                passed.append(j)
            elif not loc or loc == 'not specified':
                passed.append(j)

        return passed

    def _filter_by_applicants(self, jobs: List[Dict]) -> List[Dict]:
        """Strictly exclude jobs with > 100 applicants"""
        max_limit = self.max_applicants or 100
        passed = []

        for j in jobs:
            count = j.get('num_applicants')
            if count is not None and count > max_limit:
                continue

            desc = (j.get('description') or '').lower()
            if any(term in desc for term in [
                'over 100', '100+ applicants', '100+ people', '150+ applicants',
                '200+ applicants', 'more than 100', 'over 100 clicked apply',
                'over 100 people clicked apply', 'over 100 applicants'
            ]):
                continue

            passed.append(j)
        return passed

    def _deduplicate(self, jobs: List[Dict]) -> List[Dict]:
        """Deduplicate jobs by URL and Company+Title"""
        seen_urls = set()
        seen_keys = set()
        unique = []

        for j in jobs:
            url = (j.get('url') or '').strip()
            key = f"{(j.get('company') or '').lower()}|{(j.get('title') or '').lower()}"

            if url and url not in seen_urls and key not in seen_keys:
                seen_urls.add(url)
                seen_keys.add(key)
                unique.append(j)

        return unique

    @staticmethod
    def _sort_by_platform_priority(jobs: List[Dict]) -> List[Dict]:
        """Order: LinkedIn (1) -> Indeed (2) -> Naukri (3) -> Rest (4), then date_posted desc"""
        priority_map = {'linkedin': 1, 'indeed': 2, 'naukri': 3}

        def get_sort_key(j):
            plat = (j.get('platform') or '').lower()
            priority = priority_map.get(plat, 4)
            dt = j.get('date_posted')
            ts = 0.0
            if dt:
                if hasattr(dt, 'timestamp'):
                    try:
                        ts = dt.timestamp()
                    except Exception:
                        ts = 0.0
                elif isinstance(dt, str):
                    try:
                        parsed = datetime.fromisoformat(dt.replace('Z', '+00:00'))
                        ts = parsed.timestamp()
                    except Exception:
                        ts = 0.0
            return (priority, -ts)

        return sorted(jobs, key=get_sort_key)
