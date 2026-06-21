"""Self-contained HTML "how to get your API key(s)" guide.

Served by GET /api/jobs/platforms/setup-guide when the discovery orchestrator
needs human input — i.e. RapidAPI rejected or rate-limited the key, so platforms
could not be validated. Standalone page (not rendered inside the SPA), so the
Calm-Intelligence styling is inlined rather than pulled from tokens.css.
"""

from html import escape


def build_html(missing: list[str] | None = None, *, reason: str | None = None) -> str:
    """Render the setup guide. `missing` lists the keys/services still needed;
    `reason` is the orchestrator's classification (bad key, quota, etc.)."""
    missing = missing or ["RAPIDAPI_KEY (JSearch)"]
    reason_html = (
        f'<p class="reason">Why you are seeing this: {escape(reason)}.</p>'
        if reason
        else ""
    )
    missing_items = "\n".join(
        f"<li><code>{escape(m)}</code></li>" for m in missing
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Search — API Key Setup</title>
<style>
  :root {{
    --bg: #14141a; --surface: #1c1c25; --elevated: #23232f;
    --border: #2e2e3c; --text: #ECECF1; --text-dim: #A7A7B4;
    --accent: #6366F1; --amber: #F5A623;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: "Inter", system-ui, -apple-system, sans-serif;
    line-height: 1.6; padding: 48px 20px;
  }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  h1 {{
    font-family: "Plus Jakarta Sans", "Inter", sans-serif;
    font-size: 28px; margin: 0 0 6px;
  }}
  .lead {{ color: var(--text-dim); margin: 0 0 28px; }}
  .reason {{
    background: rgba(245,166,35,0.08); border: 1px solid rgba(245,166,35,0.3);
    border-left: 3px solid var(--amber); border-radius: 8px;
    padding: 12px 16px; color: #f0d9b5; margin: 0 0 28px;
  }}
  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 22px 24px; margin: 0 0 18px;
  }}
  h2 {{ font-size: 18px; margin: 0 0 12px; }}
  ol {{ margin: 0; padding-left: 22px; }}
  ol li {{ margin: 8px 0; }}
  code {{
    background: var(--elevated); border: 1px solid var(--border);
    border-radius: 6px; padding: 1px 6px; font-family: "JetBrains Mono", monospace;
    font-size: 0.9em; color: #cdd0ff;
  }}
  a {{ color: var(--accent); }}
  .missing {{ list-style: none; padding: 0; margin: 8px 0 0; }}
  .missing li {{ display: inline-block; margin: 4px 6px 0 0; }}
  .pill {{
    display: inline-flex; align-items: center; gap: 8px;
    background: var(--accent); color: #fff; border-radius: 999px;
    padding: 4px 12px; font-size: 13px; font-weight: 600;
  }}
  .env {{
    background: var(--elevated); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 16px; overflow-x: auto;
    font-family: "JetBrains Mono", monospace; font-size: 13px; color: #cdd0ff;
  }}
  .foot {{ color: var(--text-dim); font-size: 13px; margin-top: 28px; }}
</style>
</head>
<body>
  <div class="wrap">
    <span class="pill">Private Internet · Job Search</span>
    <h1 style="margin-top:16px">Connect a job-search API key</h1>
    <p class="lead">
      The job hunt finds listings through RapidAPI's JSearch, which aggregates
      LinkedIn, Indeed, and local boards (jobs.ch, GaijinPot, and more) under a
      single key. Discovery couldn't validate platforms because a key is missing
      or unusable — follow these steps once and it heals itself on the next run.
    </p>
    {reason_html}

    <div class="card">
      <h2>Still needed</h2>
      <ul class="missing">{missing_items}</ul>
    </div>

    <div class="card">
      <h2>1. Create a RapidAPI account</h2>
      <ol>
        <li>Go to <a href="https://rapidapi.com/auth/sign-up" target="_blank" rel="noreferrer">rapidapi.com/auth/sign-up</a> and sign up (Google/GitHub/email all work).</li>
        <li>Verify your email if prompted.</li>
      </ol>
    </div>

    <div class="card">
      <h2>2. Subscribe to JSearch</h2>
      <ol>
        <li>Open the JSearch API page: <a href="https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch" target="_blank" rel="noreferrer">rapidapi.com/.../api/jsearch</a>.</li>
        <li>Click <strong>Subscribe to Test</strong> → pick the <strong>Basic (Free)</strong> plan to start. It gives a monthly request quota that's plenty for daily discovery + searches.</li>
        <li>Confirm the subscription. You can upgrade later if you hit the quota (a <code>429</code> error).</li>
      </ol>
    </div>

    <div class="card">
      <h2>3. Copy your key</h2>
      <ol>
        <li>On any JSearch endpoint tab, find the <strong>X-RapidAPI-Key</strong> header in the code snippet on the right.</li>
        <li>Copy that value — it's a long string of letters and numbers. This is your <code>RAPIDAPI_KEY</code>.</li>
      </ol>
    </div>

    <div class="card">
      <h2>4. Set it on the server</h2>
      <p style="color:var(--text-dim);margin:0 0 10px">
        Add it to the backend environment (the <code>.env</code> the services load), then restart the agents service:
      </p>
      <div class="env">RAPIDAPI_KEY=your_key_here<br>RAPIDAPI_HOST=jsearch.p.rapidapi.com</div>
      <p style="color:var(--text-dim);margin:10px 0 0">
        Discovery runs nightly and re-validates automatically — or trigger it now
        from the server with the internal discovery endpoint.
      </p>
    </div>

    <p class="foot">
      Optional: some platforms can use a dedicated API instead of the shared
      JSearch aggregator. Those declare their own RapidAPI host and need a
      separate subscription — the same steps apply, just subscribe to that API
      and add its key. Until then, those platforms still work through JSearch.
    </p>
  </div>
</body>
</html>"""
