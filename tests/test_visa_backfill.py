import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).parents[1] / "freehire_fetch.py"
spec = importlib.util.spec_from_file_location("freehire_fetch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def legacy_fingerprint(job: dict) -> str:
    enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
    meaningful = {
        "title": job.get("title"),
        "company": job.get("company_name") or job.get("company"),
        "location": job.get("location"),
        "description": job.get("description"),
        "source_url": job.get("source_url") or job.get("apply_url") or job.get("application_url"),
        "freehire_url": job.get("freehire_url") or job.get("url"),
        "external_id": job.get("external_id") or job.get("source_job_id"),
        "employment_type": enrichment.get("employment_type") or job.get("employment_type"),
        "seniority": enrichment.get("seniority"),
        "experience_years_min": enrichment.get("experience_years_min"),
        "company_type": enrichment.get("company_type"),
    }
    raw = json.dumps(meaningful, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class VisaBackfillTests(unittest.TestCase):
    def test_existing_job_with_explicit_visa_language_reemits_once(self):
        job = {
            "public_slug": "existing-sponsored-role",
            "title": "AI Engineer",
            "company_name": "Acme",
            "location": "Singapore",
            "description": "Visa sponsorship is available for this role.",
        }
        seen = {
            job["public_slug"]: {
                "fingerprint": legacy_fingerprint(job),
                "last_seen": "2026-10-10T00:00:00Z",
            }
        }

        events, _ = mod.classify_events([job], seen, "2026-10-11T00:00:00Z", bootstrap=False)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "CHANGED")
        self.assertEqual(events[0]["visa_signal"], "positive")

    def test_existing_job_without_visa_language_does_not_reemit(self):
        job = {
            "public_slug": "existing-no-visa-role",
            "title": "AI Engineer",
            "company_name": "Acme",
            "location": "Singapore",
            "description": "Build production AI services with Python and FastAPI.",
        }
        seen = {
            job["public_slug"]: {
                "fingerprint": legacy_fingerprint(job),
                "last_seen": "2026-10-10T00:00:00Z",
            }
        }

        events, _ = mod.classify_events([job], seen, "2026-10-11T00:00:00Z", bootstrap=False)

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
