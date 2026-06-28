"""Bank-account linking module.

Connects a user's German bank (Sparkasse, Volksbank, … via GoCardless Bank
Account Data / PSD2) and polls it daily, rendering each account's month into a
statement-shaped brain memory the existing BankAdviser already understands.

Layers:
  gocardless.py        — thin REST client over the GoCardless API
  statement_format.py  — render GoCardless data → German-statement text
  db.py                — schema bootstrap + row CRUD (mirrors 0028_bank_link.sql)
  service.py           — consent flow, daily sync, memory upsert, fan-out
  routes.py            — REST API mounted at /api/bank
"""
