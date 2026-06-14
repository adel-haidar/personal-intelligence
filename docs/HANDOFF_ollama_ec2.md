# Handoff — Provision Ollama + bge-m3 on EC2

**Audience:** Claude Code running **on the production EC2 host** (`~/personal-intelligence`,
Ubuntu, systemd). This is a **one-time host setup**, exactly like the FFmpeg install
documented in the root `CLAUDE.md` ("Required system packages (one-time)").

## Why
We are giving every user their own isolated "brain" (the mcp-memory store) and removing
the brain's dependency on AWS Bedrock for embeddings, so a brain can run on any host
(AWS now, user-owned hardware later). Step one is a **local, self-hosted embedding
service**. The model is **bge-m3** (1024-d, multilingual — it matches the existing
`vector(1024)` column, so no schema change), served by **Ollama** on localhost.

## Goal (acceptance criteria)
1. Ollama installed and running as a systemd service, **bound to `127.0.0.1:11434` only**.
2. `bge-m3` pulled.
3. `POST /api/embed` returns a **1024-dimension** vector.
4. Service enabled on boot.

## SCOPE BOUNDARY — read before doing anything
- This is **host provisioning ONLY**. Do **NOT** edit any Python under `src/` or `agents/`,
  do **NOT** change the embedding code path, and do **NOT** run any re-embedding backfill.
  Those happen later from the dev machine via the normal git → GitHub Actions deploy.
  **Editing code directly on EC2 will be overwritten by the next deploy's `git pull`.**
- Do **NOT** expose port `11434` publicly — no nginx `location`, no security-group change.
  Localhost only.
- Do **NOT** touch the `personal-intelligence-api` / `personal-intelligence-agents` systemd
  units or the nginx config. Ollama is a separate, independent unit.

---

## Steps

### 0. Pre-flight — capture state, stop if tight
```bash
free -h          # need ~2 GB+ headroom; bge-m3 is ~1 GB resident
df -h /          # need ~3 GB free (model + binary)
uname -m         # informational — Ollama supports x86_64 and arm64
```
If RAM or disk is tight, **STOP and report back** before installing.

### 1. Install Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
```
On Linux this installs the binary, creates an `ollama` system user, and installs + enables
a systemd unit `ollama.service` that listens on `127.0.0.1:11434` by default.

### 2. Confirm it is running and localhost-bound
```bash
systemctl is-enabled ollama
systemctl status ollama --no-pager
ss -tlnp | grep 11434      # MUST show 127.0.0.1:11434 — NOT 0.0.0.0
```
If it shows `0.0.0.0`, force localhost explicitly:
```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
EOF
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

### 3. (Recommended) Keep the model resident
By default Ollama unloads a model after ~5 min idle, adding reload latency to a service
that's hit regularly. Pin it loaded (trade-off: ~1 GB RAM stays resident — skip if RAM is tight):
```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/keepalive.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_KEEP_ALIVE=-1"
EOF
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

### 4. Pull the model
```bash
ollama pull bge-m3
ollama list      # RECORD the ID/digest — the same model must be used everywhere (home boxes later)
```

### 5. Verify — the acceptance test
```bash
curl -s http://127.0.0.1:11434/api/embed \
  -d '{"model":"bge-m3","input":"hello world"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('dims=', len(d['embeddings'][0]))"
```
**Must print `dims= 1024`.** Anything else → **STOP and report**.

---

## Leave the host in this state (the code side assumes it)
- Embedder reachable at `http://127.0.0.1:11434`, endpoint `POST /api/embed`.
- Model name exactly `bge-m3`, dimension `1024`.

The later Python cutover will read these via env vars (`EMBEDDING_URL`, `EMBEDDING_MODEL`)
and will be deployed through GitHub Actions — **not** part of this handoff. Do not set those
env vars or change app config here.

## Report back (green-light for the code cutover)
Paste:
- `ollama --version`
- `ollama list`
- the `ss -tlnp | grep 11434` line (proving localhost bind)
- the `dims= 1024` result

## Rollback (only if asked)
```bash
sudo systemctl disable --now ollama
ollama rm bge-m3
sudo rm -f /etc/systemd/system/ollama.service.d/override.conf \
           /etc/systemd/system/ollama.service.d/keepalive.conf
sudo systemctl daemon-reload
# Full uninstall: remove /usr/local/bin/ollama (or /usr/bin/ollama) and the ollama user.
```
