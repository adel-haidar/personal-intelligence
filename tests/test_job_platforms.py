"""Tests for the job-platform discovery helpers and search-time filtering.

Pure-function coverage (no DB / no network):
- slugify: stable platform keys from names/domains
- _norm_domain: strips scheme/path/www
- _build_platforms: merges LLM proposals with live-sampled publishers, marking
  confirmed boards available + top-ranked and proposed-but-absent ones unavailable
- _listing_matches_platforms: matches a listing to a selection by name or domain
- setup_guide.build_html: renders a non-empty HTML page listing the missing keys
"""

import unittest

from assistant.job.agent import _listing_matches_platforms
from assistant.job.models import JobListing
from assistant.job.platforms.discovery import (
    _build_platforms,
    _norm_domain,
    slugify,
)
from assistant.job.platforms.setup_guide import build_html


def _listing(**kw) -> JobListing:
    base = dict(
        platform="LinkedIn", title="Engineer", company="Acme",
        location="Zurich", country="Switzerland",
        job_url="https://www.linkedin.com/jobs/view/1",
    )
    base.update(kw)
    return JobListing(**base)


class TestSlugAndDomain(unittest.TestCase):
    def test_slugify_domain(self):
        self.assertEqual(slugify("linkedin.com"), "linkedin")
        self.assertEqual(slugify("www.indeed.com"), "indeed")

    def test_slugify_name_with_spaces(self):
        self.assertEqual(slugify("Gaijin Pot"), "gaijin_pot")

    def test_slugify_never_empty(self):
        self.assertTrue(slugify(""))

    def test_norm_domain(self):
        self.assertEqual(_norm_domain("https://www.jobs.ch/en/jobs"), "jobs.ch")
        self.assertEqual(_norm_domain("WWW.Indeed.com"), "indeed.com")
        self.assertEqual(_norm_domain(None), "")


class TestBuildPlatforms(unittest.TestCase):
    def setUp(self):
        self.proposed = [
            {"name": "LinkedIn", "domain": "linkedin.com"},
            {"name": "jobs.ch", "domain": "jobs.ch"},
            {"name": "GhostBoard", "domain": "ghost.example"},
        ]
        self.sampled = [("LinkedIn", "linkedin.com"), ("Indeed", "indeed.com")]

    def test_confirmed_proposal_is_available_and_top_ranked(self):
        plats = {p.platform_key: p for p in
                 _build_platforms("CH", self.proposed, self.sampled, validated=True)}
        self.assertTrue(plats["linkedin"].available)
        # Highest rank goes to the first confirmed LLM proposal.
        self.assertGreaterEqual(plats["linkedin"].rank, 100)

    def test_unconfirmed_proposal_kept_but_unavailable(self):
        plats = {p.platform_key: p for p in
                 _build_platforms("CH", self.proposed, self.sampled, validated=True)}
        # GhostBoard was proposed but never seen in the sample.
        self.assertIn("ghost_example", plats)
        self.assertFalse(plats["ghost_example"].available)

    def test_extra_sampled_publisher_added(self):
        plats = {p.platform_key: p for p in
                 _build_platforms("CH", self.proposed, self.sampled, validated=True)}
        # Indeed was not proposed by the LLM but JSearch returned it.
        self.assertIn("indeed", plats)
        self.assertTrue(plats["indeed"].available)

    def test_unvalidated_keeps_all_proposals_available(self):
        # No live sample (e.g. no key) → proposals kept on trust.
        plats = _build_platforms("CH", self.proposed, [], validated=False)
        self.assertTrue(all(p.available for p in plats))
        # ...and no extra publishers are invented.
        self.assertEqual(len(plats), len(self.proposed))


class TestListingMatch(unittest.TestCase):
    def test_match_by_publisher_name(self):
        listing = _listing(publisher="LinkedIn", apply_publishers=["LinkedIn"])
        self.assertTrue(_listing_matches_platforms(listing, {"linkedin"}, set()))

    def test_match_by_domain_in_url(self):
        listing = _listing(publisher="Some Board")
        self.assertTrue(_listing_matches_platforms(listing, set(), {"linkedin.com"}))

    def test_no_match(self):
        listing = _listing(publisher="LinkedIn", apply_publishers=[])
        self.assertFalse(_listing_matches_platforms(listing, {"jobs.ch"}, {"jobs.ch"}))


class TestSetupGuide(unittest.TestCase):
    def test_renders_missing_keys(self):
        html = build_html(["RAPIDAPI_KEY (JSearch)"])
        self.assertIn("<!doctype html>", html)
        self.assertIn("RAPIDAPI_KEY", html)

    def test_defaults_when_none(self):
        html = build_html(None)
        self.assertIn("RAPIDAPI_KEY", html)


if __name__ == "__main__":
    unittest.main()
