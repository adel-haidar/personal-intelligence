# CLAUDE.md — personal-intelligence

## Standing Rules (apply to every task, without being asked)

### After completing any fix, feature, or change:

1. `git add -A`
2. `git commit -m "<conventional commit message>"`
   - Backend-only change: prefix `feat(backend):` / `fix(backend):`
   - Dashboard-only change: prefix `feat(dashboard):` / `fix(dashboard):`
   - Both changed: use `[deploy-all]` anywhere in the message
3. `git push origin main`
   - If push fails with `Permission denied (publickey)`, the SSH agent isn't running.
     Run everything in **one shell call** so the agent environment persists:
     ```
     eval $(ssh-agent) && ssh-add ~/.ssh/github && git push origin main
     ```
     Each Bash tool call is a separate shell — `eval $(ssh-agent)` in one call and
     `git push` in the next will always fail because `SSH_AUTH_SOCK` is lost.

**That's it.** GitHub Actions handles the rest automatically:
- Backend changes → SSH into EC2, git pull, pip install, restart systemd services
- Dashboard changes → npm build, S3 sync, CloudFront cache invalidation
- `[deploy-all]` in the commit message → both pipelines run

Do NOT manually SSH into EC2 or run deploy commands unless GitHub Actions is broken
and you have been explicitly told to bypass it.

---

## Project Structure

```
personal-intelligence/
├── dashboard/          ← Vue 3 app (S3 + CloudFront)
├── src/backend/        ← FastMCP + Python services (EC2)
├── .github/workflows/
│   └── deploy.yml      ← CI/CD pipeline
├── DEPLOY.md           ← Manual deploy reference (fallback only)
└── .ssh/               ← SSH keys (fallback only)
```

---

## Key URLs
- Production: https://adel-intelligence.com
- Dashboard: https://adel-intelligence.com (or subdomain — adjust as needed)
