# AWS Deployment Guide — personal-intelligence

## How it works

```
Browser
  │
  ▼
CloudFront  (adel-intelligence.com)
  │
  ├── /api/*  /mcp/*  /oauth/*  /.well-known/*  ──►  ALB  ──►  EC2 nginx  ──►  API :8000
  │                                                                         ──►  Agents :8001
  │
  ├── /openclaw/*  /banking/*  (your existing services)  ──►  ALB  ──►  EC2 nginx  ──► ...
  │
  └── /* (everything else)  ──►  S3 bucket  (Vue frontend)
```

**Why this layout:**
- The Vue app is a bunch of static files — S3 + CloudFront is the cheapest and fastest way to serve them globally.
- Everything stays on `adel-intelligence.com` (no subdomains), so no CORS configuration is needed.
- Your existing services (openclaw, banking, etc.) are not touched — CloudFront just forwards those paths to the ALB the same way it does now.

---

## What you need before starting

- AWS CLI installed and configured on your local machine (`aws configure` with your IAM credentials)
- SSH access to the EC2 instance
- Node.js installed locally (to build the frontend)
- The domain `adel-intelligence.com` already in Route 53 ✓
- An ALB already set up ✓
- EC2 with nginx already running ✓

---

## Part 1 — AWS Console (one-time setup)

### Step 1: Request a TLS certificate in us-east-1

CloudFront only accepts certificates from the **us-east-1** region, even though everything else is in eu-central-1.

1. Open the AWS Console. In the top-right region selector, switch to **US East (N. Virginia)**.
2. Open **Certificate Manager** → **Request certificate**.
3. Choose **Request a public certificate** → **Next**.
4. Under *Fully qualified domain name*, enter:
   - `adel-intelligence.com`
   - Click **Add another name** → `*.adel-intelligence.com`
5. Validation method: **DNS validation** (recommended).
6. Click **Request**.
7. On the certificate detail page, click **Create records in Route 53**. AWS adds the required DNS records automatically.
8. Wait 2–5 minutes. Refresh the page until the status shows **Issued**.

> Your EC2/ALB may already have a separate certificate in eu-central-1 — leave that one alone. This new certificate is only for CloudFront.

---

### Step 2: Create an S3 bucket for the frontend

1. Switch back to **eu-central-1**.
2. Open **S3** → **Create bucket**.
3. Bucket name: `adel-intelligence-frontend`
4. Region: **eu-central-1**
5. **Block all public access**: leave all four boxes checked. CloudFront will access the bucket privately — no public access needed.
6. Leave everything else as default → **Create bucket**.

---

### Step 3: Create the CloudFront distribution

CloudFront is the single entry point for `adel-intelligence.com`. It decides whether a request goes to S3 (frontend) or the ALB (API).

#### 3a. Open CloudFront → Create distribution

**Origin 1 — S3 (the Vue frontend)**

| Setting | Value |
|---|---|
| Origin domain | Select your `adel-intelligence-frontend` S3 bucket |
| Origin access | **Origin access control settings (recommended)** |
| Origin access control | Click **Create new OAC** → accept defaults → **Create** |

Leave everything else on the origin at default.

**Default cache behavior** (this handles `/*` — the frontend)

| Setting | Value |
|---|---|
| Viewer protocol policy | **Redirect HTTP to HTTPS** |
| Allowed HTTP methods | GET, HEAD |
| Cache policy | **CachingOptimized** |

**Distribution settings**

| Setting | Value |
|---|---|
| Alternate domain names | `adel-intelligence.com` |
| Custom SSL certificate | Select the certificate you created in Step 1 |
| Default root object | `index.html` |

Click **Create distribution**. It takes about 5 minutes to deploy. You will see a yellow banner — keep the page open for the next step.

#### 3b. Attach the S3 bucket policy

After the distribution is created, CloudFront shows a banner: *"The S3 bucket policy needs to be updated."*

1. Click **Copy policy**.
2. Open **S3** → your bucket → **Permissions** tab → **Bucket policy** → **Edit**.
3. Paste the policy → **Save changes**.

This allows CloudFront (and only CloudFront) to read files from the bucket.

---

### Step 4: Add the ALB as a second origin

Go to CloudFront → your distribution → **Origins** tab → **Create origin**.

| Setting | Value |
|---|---|
| Origin domain | Your ALB's DNS name (e.g. `my-alb-abc123.eu-central-1.elb.amazonaws.com`) |
| Protocol | **HTTPS only** if your ALB has a cert, otherwise **HTTP only** |
| Leave everything else | default |

Click **Create origin**.

---

### Step 5: Add path behaviors for the backend

These behaviors tell CloudFront to forward certain paths to the ALB instead of S3.

Go to **Behaviors** tab → **Create behavior** — create one for each row below. **Order matters**: more specific paths must be listed before the default `/*`.

| Path pattern | Origin | Cache policy | Allowed HTTP methods |
|---|---|---|---|
| `/api/*` | ALB | CachingDisabled | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| `/mcp/*` | ALB | CachingDisabled | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| `/oauth/*` | ALB | CachingDisabled | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| `/.well-known/*` | ALB | CachingDisabled | GET, HEAD |
| `/openclaw/*` | ALB | CachingDisabled | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| `/banking/*` | ALB | CachingDisabled | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |

> Add any other backend paths you have (`/hermes/*`, etc.) to this list.

For every behavior above, also set:
- **Viewer protocol policy**: Redirect HTTP to HTTPS
- **Origin request policy**: **AllViewer** — this passes all headers, cookies, and query strings to the ALB so your services see real request data

---

### Step 6: Fix browser refreshes on Vue routes

Without this, refreshing the page on any Vue route (e.g. `/dashboard`) returns a 403 error from S3 because that path doesn't exist as a file.

Go to CloudFront → your distribution → **Error pages** tab → **Create custom error response**.

Do this **twice** — once for 403, once for 404:

| Setting | Value |
|---|---|
| HTTP error code | 403 (then repeat for 404) |
| Customize error response | Yes |
| Response page path | `/index.html` |
| HTTP response code | **200** |

---

### Step 7: Lock down the ALB security group

Right now anyone who knows your ALB's DNS name can bypass CloudFront and hit your backend directly. Fix this by restricting the ALB to only accept traffic from CloudFront.

1. Go to **EC2** → **Load Balancers** → your ALB → **Security** tab → click the security group.
2. **Inbound rules** → **Edit inbound rules**.
3. Find the rule allowing port 443 (and/or 80) from `0.0.0.0/0`.
4. Change the source from `0.0.0.0/0` to the AWS-managed CloudFront prefix list:
   - In the source box, search for **CloudFront** — you will see a managed prefix list like `pl-xxxxxxxx (com.amazonaws.global.cloudfront.origin-facing)`.
   - Select it.
5. **Save rules**.

From this point, only CloudFront can reach your ALB on that port.

---

### Step 8: Update Route 53

Switch the domain from pointing at the ALB to pointing at CloudFront.

1. Go to **Route 53** → **Hosted zones** → `adel-intelligence.com`.
2. Find the `A` record for `adel-intelligence.com` (the root record).
3. Click **Edit record**.
4. Make sure **Alias** is toggled on.
5. Route traffic to: **Alias to CloudFront distribution**.
6. Select your distribution from the dropdown.
7. **Save**.

DNS updates within AWS propagate in under a minute.

---

## Part 2 — EC2 Setup

SSH into your EC2 instance for all steps in this section.

---

### Step 9: Transfer the code

Run this from your **local machine**:

```bash
rsync -av \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude '__pycache__' \
  --exclude '.git' \
  /home/adel/dev/personal-intelligence/ \
  ec2-user@<EC2_HOST>:/home/ec2-user/personal-intelligence/
```

Alternatively, push the repo to GitHub and clone it on the EC2.

---

### Step 10: Create the .env file on EC2

```bash
cp /home/ec2-user/personal-intelligence/.env.example \
   /home/ec2-user/personal-intelligence/.env

nano /home/ec2-user/personal-intelligence/.env
```

Fill in every blank value. The critical ones:

| Variable | Where to find it |
|---|---|
| `DB_HOST` | RDS console → your database → Endpoint |
| `DB_PASSWORD` | The password you set when creating the RDS instance |
| `SECRET_KEY` | Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `MS_CLIENT_ID` / `MS_CLIENT_SECRET` | Azure portal → App registrations |
| `MCP_MEMORY_CLIENT_ID` / `MCP_MEMORY_REFRESH_TOKEN` | From the OAuth flow after first login |

---

### Step 11: Set up Python virtual environments

**Service A — the API (port 8000):**

```bash
cd /home/ec2-user/personal-intelligence
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
deactivate
```

**Service B — the agents (port 8001):**

python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e .
cd /home/ec2-user/personal-intelligence/agents
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
deactivate
```

The `playwright install chromium` step is required for the job-search scrapers. It downloads a headless browser (~200 MB) — only run it once.

---

### Step 12: Install and start the systemd services

```bash
sudo cp /home/ec2-user/personal-intelligence/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable personal-intelligence-api personal-intelligence-agents
sudo systemctl start personal-intelligence-api personal-intelligence-agents
```

Check that both started cleanly:

```bash
sudo systemctl status personal-intelligence-api
sudo systemctl status personal-intelligence-agents
```

If a service failed, check its logs:

```bash
journalctl -u personal-intelligence-api -n 50
journalctl -u personal-intelligence-agents -n 50
```

Common causes of failure: a missing or misspelled value in `.env`, or the wrong Python path in the venv.

---

### Step 13: Update nginx

Open your existing nginx config for `adel-intelligence.com`:

```bash
sudo nano /etc/nginx/conf.d/adel-intelligence.conf
```

Inside the existing `server` block, add these location blocks **alongside** your existing ones for openclaw, banking, etc.:

```nginx
# personal-intelligence REST API
location /api/ {
    proxy_pass         http://127.0.0.1:8000;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    client_max_body_size 100M;
}

# OAuth authorize / token / register
location /oauth/ {
    proxy_pass         http://127.0.0.1:8000;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
}

# OAuth discovery document
location /.well-known/ {
    proxy_pass         http://127.0.0.1:8000;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
}

# MCP server (uses SSE streaming — buffering must be off)
location /mcp/ {
    proxy_pass         http://127.0.0.1:8000;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_buffering    off;
    proxy_read_timeout 300s;
}
```

> **Note:** Do not add a `root` directive or a `location /` block that serves static files — the frontend now lives in S3, not on disk.

Test the config and reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Part 3 — Deploy the Frontend

Run these steps on your **local machine**.

---

### Step 14: Build the Vue app

```bash
cd /home/adel/dev/personal-intelligence/frontend
npm install
npm run build
```

The output goes to `frontend/dist/`.

---

### Step 15: Upload to S3

Two separate uploads so that `index.html` always gets fetched fresh while hashed asset files (JS, CSS) are cached for a full year:

```bash
# Hashed assets — cache for 1 year
aws s3 sync frontend/dist/ s3://adel-intelligence-frontend/ \
  --delete \
  --exclude "index.html" \
  --cache-control "max-age=31536000,immutable" \
  --region eu-central-1

# index.html — never cache (so users always get the latest version)
aws s3 cp frontend/dist/index.html s3://adel-intelligence-frontend/index.html \
  --cache-control "no-cache, no-store, must-revalidate" \
  --region eu-central-1
```

---

### Step 16: Invalidate the CloudFront cache

CloudFront caches files at the edge. After uploading, tell it to clear the cache:

```bash
aws cloudfront create-invalidation \
  --distribution-id <YOUR_DISTRIBUTION_ID> \
  --paths "/*"
```

Replace `<YOUR_DISTRIBUTION_ID>` with the ID shown on the CloudFront distribution page (format: `EXXXXXXXXXX`).

The invalidation takes about 1–2 minutes. After that, users will see the new version.

---

## Part 4 — Verify everything works

Run these from your local machine after completing all steps above.

**Frontend loads:**
```bash
curl -I https://adel-intelligence.com
# Expect: HTTP/2 200
# Expect header: x-cache: Miss from cloudfront (first hit) or Hit from cloudfront (cached)
```

**OAuth discovery:**
```bash
curl https://adel-intelligence.com/.well-known/oauth-authorization-server
# Expect: JSON with issuer, authorization_endpoint, token_endpoint
```

**API reachable (will return 401 without a token — that's correct):**
```bash
curl -i https://adel-intelligence.com/api/memory
# Expect: HTTP 401 Unauthorized
```

**MCP endpoint reachable:**
```bash
curl -i https://adel-intelligence.com/mcp/mcp
# Expect: an MCP protocol response, not a 404
```

Also open `https://adel-intelligence.com` in a browser, navigate to a few pages, and hard-refresh (Ctrl+Shift+R) — it should load correctly every time.

---

## Re-deploying after changes

### Backend changed (Python code)

```bash
# On the EC2
cd /home/ec2-user/personal-intelligence
git pull   # or rsync from local

sudo systemctl restart personal-intelligence-api
# and/or
sudo systemctl restart personal-intelligence-agents
```

No CloudFront change needed — the backend is not cached.

### Frontend changed (Vue code)

```bash
# On your local machine
cd /home/adel/dev/personal-intelligence/frontend
npm run build

aws s3 sync dist/ s3://adel-intelligence-frontend/ \
  --delete \
  --exclude "index.html" \
  --cache-control "max-age=31536000,immutable" \
  --region eu-central-1

aws s3 cp dist/index.html s3://adel-intelligence-frontend/index.html \
  --cache-control "no-cache, no-store, must-revalidate" \
  --region eu-central-1

aws cloudfront create-invalidation \
  --distribution-id <YOUR_DISTRIBUTION_ID> \
  --paths "/*"
```

### New Python dependency added

```bash
# On the EC2, in the right venv
source /home/ec2-user/personal-intelligence/.venv/bin/activate
pip install -e .
deactivate
sudo systemctl restart personal-intelligence-api
```

---

## Marketing website — `private-internet.io`

The long-scroll marketing site in `website/` (Vue 3 + Vite) is a **separate
deployable** from the dashboard. It is served at the apex `private-internet.io`;
the platform/dashboard it links to lives at `app.private-internet.io`.

CI/CD: the `deploy-website` job in `.github/workflows/deploy.yml` mirrors the
dashboard job (npm build → S3 sync → CloudFront invalidation). It is **opt-in** —
it runs only when the commit message starts with `feat(website)` / `fix(website)`
or contains `[deploy-all]`, so backend/dashboard/generic commits never touch it.

**One-time AWS setup** (same recipe as the dashboard — Steps 1, 2, 3, 6, 8 above,
but for the new domain): ACM cert for `private-internet.io` in **us-east-1**, a
new S3 bucket, a new CloudFront distribution (with the SPA 404→`/index.html`
behavior from Step 6), and Route 53 records for `private-internet.io`.

**Repo secrets the job needs** (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `S3_WEBSITE_BUCKET` | the new website bucket name |
| `WEBSITE_CLOUDFRONT_DISTRIBUTION_ID` | the new distribution's ID |

(`AWS_ROLE_ARN` is reused from the existing OIDC setup — no new role needed,
though the role's policy must allow `s3:*` on the new bucket and
`cloudfront:CreateInvalidation` on the new distribution.)

**Manual deploy** (fallback, from your local machine):

```bash
cd /home/adel/dev/personal-intelligence/website
npm run build
aws s3 sync dist/ s3://<WEBSITE_BUCKET>/ --delete \
  --exclude "index.html" --cache-control "max-age=31536000,immutable" --region eu-central-1
aws s3 cp dist/index.html s3://<WEBSITE_BUCKET>/index.html \
  --cache-control "no-cache, no-store, must-revalidate" --region eu-central-1
aws cloudfront create-invalidation --distribution-id <WEBSITE_DISTRIBUTION_ID> --paths "/*"
```

---

## Troubleshooting

**Refreshing on a Vue route gives a blank page or 403**
→ Step 6 (CloudFront error pages) is missing. Both 403 and 404 must return `/index.html` with HTTP 200.

**API calls return 502 Bad Gateway**
→ The personal-intelligence-api service is down. On the EC2: `sudo systemctl status personal-intelligence-api` and `journalctl -u personal-intelligence-api -n 50`.

**API calls return 403 from CloudFront**
→ The request is hitting the S3 origin instead of the ALB. Check that the `/api/*` behavior exists in CloudFront and is listed before the default `/*` behavior.

**The site loads but API calls return "Network Error" in the browser**
→ The frontend is making API calls correctly (same domain, no CORS needed), but nginx may not be running or the port 8000 service is down. Check nginx: `sudo systemctl status nginx`.

**MCP connections drop after about 60 seconds**
→ CloudFront has a hard 60-second origin response timeout. Long-lived MCP SSE sessions may be affected. If this happens consistently, configure your MCP client to reconnect on disconnect. The server handles reconnects cleanly.

**Cannot reach ALB after locking down the security group (Step 7)**
→ You may have blocked your own access. Add a temporary inbound rule allowing your IP on port 443 while you debug. Re-check that the CloudFront prefix list is correct: `com.amazonaws.global.cloudfront.origin-facing`.
