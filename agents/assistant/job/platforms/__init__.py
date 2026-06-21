"""Per-country job-platform discovery + catalog.

A daily hub-and-spoke orchestrator (`discovery.orchestrate`) finds the best job
boards for each country — an LLM proposes them, a live JSearch sample validates
which actually return results — and persists them via `catalog`. The dashboard
reads the catalog to populate a per-country platform multi-select, and the job
search filters JSearch results to the publishers the user selected.
"""
