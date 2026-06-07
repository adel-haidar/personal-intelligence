# Migration Runbook — adel-intelligence → personal-intelligence

## Overview

This runbook migrates three separate services into the `personal-intelligence` monorepo.

| Old service | Old port | New service | New port |
|---|---|---|---|
| `mcp-memory` | 8000 | `personal-intelligence-api` | 8000 |
| `mcp-file-upload` | 8002 | _(merged into api)_ | — |
| `adel-agent` | 8001 | `personal-intelligence-agents` | 8001 (unchanged) |

Port 8000 is reused. Shut down the old `mcp-memory` service **before** starting the new API.

---

## Phase 1 — Local Development (`/home/adel/dev/`)

### 1. Create the repo (already done if you are reading this)

```bash
cd /home/adel/dev/personal-intelligence
git init
git add .
git commit -m "Initial personal-intelligence consolidation"
```

### 2. Verify source was copied correctly

```bash
# Service A source
ls src/personal_intelligence/
# Expected: __init__.py  api.py  auth/  config.py  database.py  memory/

# Agents source
ls agents/assistant/
# Expected: banking/  email/  job/  shared/  __init__.py

# Frontend source
ls frontend/src/
# Expected: App.vue  components/  composables/  config/  data/  main.ts  router/  style.css  utils/  views/
```

### 3. Create the unified `.env`

```bash
cp .env.example .env
# Edit .env and fill in the real values, merging:
#   /home/adel/dev/mcp-memory/.env       (DB_*, SECRET_KEY)
#   /home/adel/dev/agentic-assistant/.env (MS_*, MCP_MEMORY_*)
```

### 4. Set up Service A virtual environment

```bash
cd /home/adel/dev/personal-intelligence
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 5. Set up Service B (agents) virtual environment

```bash
cd /home/adel/dev/personal-intelligence/agents
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed for jobs.ch / StepStone scrapers
```

### 6. Smoke-test Service A locally

```bash
cd /home/adel/dev/personal-intelligence
source .venv/bin/activate
uvicorn personal_intelligence.api:app --port 8000 --reload
```

Expected startup output: DB tables created, MCP server mounted at `/mcp`.

Verify:
```bash
curl http://localhost:8000/.well-known/oauth-authorization-server
curl http://localhost:8000/mcp/mcp   # should return MCP protocol response
```

### 7. Smoke-test Service B locally

```bash
cd /home/adel/dev/personal-intelligence/agents
source .venv/bin/activate
uvicorn main:app --port 8001
```

```bash
curl http://localhost:8001/
# Expected: {"status": "ok"}
```

### 8. Build the frontend

```bash
cd /home/adel/dev/personal-intelligence/frontend
npm install
npm run build
# Output in frontend/dist/
```

---

## Phase 2 — Deploy to EC2 (`/home/ec2-user/`)

### 9. Transfer files to EC2

```bash
# Option A: rsync
rsync -av --exclude '.venv' --exclude 'node_modules' --exclude '__pycache__' \
  /home/adel/dev/personal-intelligence/ \
  ec2-user@<EC2_HOST>:/home/ec2-user/personal-intelligence/

# Option B: push to git remote and pull on EC2
#   git remote add origin git@github.com:adelh/personal-intelligence.git
#   git push -u origin main
#   (on EC2) git clone git@github.com:adelh/personal-intelligence.git
```

### 10. On EC2: set up venvs and install deps

```bash
# Service A
cd /home/ec2-user/personal-intelligence
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Service B
cd /home/ec2-user/personal-intelligence/agents
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 11. Create the unified .env on EC2

```bash
cp /home/ec2-user/personal-intelligence/.env.example /home/ec2-user/personal-intelligence/.env
# Fill in real values:
#   DB_* from old mcp-memory .env
#   MS_*, MCP_MEMORY_* from old adel-agent .env
nano /home/ec2-user/personal-intelligence/.env
```

### 12. Install systemd unit files

```bash
sudo cp /home/ec2-user/personal-intelligence/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 13. Stop old services

```bash
sudo systemctl stop mcp-memory.service mcp-file-upload.service adel-agent.service
sudo systemctl disable mcp-memory.service mcp-file-upload.service adel-agent.service
```

> **Note:** Port 8000 is now free for the new API.

### 14. Start new services

```bash
sudo systemctl start personal-intelligence-api.service
sudo systemctl start personal-intelligence-agents.service
sudo systemctl enable personal-intelligence-api.service personal-intelligence-agents.service
```

Check status:
```bash
sudo systemctl status personal-intelligence-api.service
sudo systemctl status personal-intelligence-agents.service
journalctl -u personal-intelligence-api.service -n 50
journalctl -u personal-intelligence-agents.service -n 50
```

### 15. Update nginx

```bash
sudo cp /home/ec2-user/personal-intelligence/nginx/personal-intelligence.conf \
    /etc/nginx/conf.d/personal-intelligence.conf

# Remove or disable old config if it exists
sudo rm -f /etc/nginx/conf.d/mcp-memory.conf
sudo rm -f /etc/nginx/conf.d/adel-intelligence.conf

sudo nginx -t && sudo systemctl reload nginx
```

### 16. Create uploads directory

```bash
mkdir -p /home/ec2-user/personal-intelligence/uploads
```

---

## Phase 3 — Verification

### 17. Verify cron job (email sync)

```bash
crontab -l
# Should contain: */15 * * * * curl -s http://localhost:8001/email/sync
# If missing, add:
# (crontab -l; echo "*/15 * * * * curl -s http://localhost:8001/email/sync") | crontab -
```

Test manually:
```bash
curl -s http://localhost:8001/email/sync
```

### 18. Verify MCP connection (Claude Desktop)

The Claude Desktop config still points to `https://adel-intelligence.com/mcp/mcp`.
No changes needed — the new Service A mounts FastMCP at the same path.

Test:
```bash
curl -s https://adel-intelligence.com/mcp/mcp
# Should return MCP protocol response (not 404)
```

### 19. Verify new memory text endpoint

```bash
# First get a token (or use an existing one from localStorage in the dashboard)
TOKEN="your-access-token"

curl -s -X POST https://adel-intelligence.com/api/memory/text \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Migration test","content":"This memory was saved via the new API.","tags":["test","migration"]}'
# Expected: {"memory_id": "..."}
```

### 20. Verify file upload

```bash
curl -s -X POST https://adel-intelligence.com/api/file \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/test.txt"
# Expected: {"status":"ok","memory_id":"...","filename":"...","size":...}
```

### 21. Verify memory list

```bash
curl -s "https://adel-intelligence.com/api/memory?page=1&page_size=5" \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"items":[...],"total":...,"page":1,"pages":...}
```

### 22. Verify OAuth flow (Claude.ai custom connector)

1. Open Claude.ai → Settings → Integrations
2. Find the existing `adel-intelligence.com` connector
3. Confirm it still shows as "Connected" — no token invalidation should occur because the same DB tables are in use
4. If disconnected, re-authorize through the existing OAuth flow

---

## Rollback

If the new services fail to start cleanly:

```bash
sudo systemctl stop personal-intelligence-api.service personal-intelligence-agents.service
sudo systemctl start mcp-memory.service mcp-file-upload.service adel-agent.service

# Restore old nginx config
sudo cp /etc/nginx/conf.d/adel-intelligence.conf.bak /etc/nginx/conf.d/adel-intelligence.conf
sudo nginx -t && sudo systemctl reload nginx
```

> Backup old nginx config before step 15: `sudo cp /etc/nginx/conf.d/*.conf /etc/nginx/conf.d/*.conf.bak`
