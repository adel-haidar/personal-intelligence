# PHASE 2 — Registration & Email Verification
## Agent: Claude Code
## Depends on: Phase 1 (SES must exist, DB must be reachable)

---

## Goal
Build the complete user registration flow: form submission → email verification → account activation. Extend the existing OAuth 2.1 auth server to handle multi-user registration with plan assignment.

---

## Task 1 — Users Table Migration

Create: `backend/alembic/versions/0006_saas_users.py`

```sql
-- Extend existing users table (or create if missing)
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(256);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(128);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_sent_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(128);
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(32) DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS registration_ip VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ;

-- Plan limits table
CREATE TABLE IF NOT EXISTS plan_limits (
  plan VARCHAR(32) PRIMARY KEY,
  max_memories INT DEFAULT 50,
  max_posts_per_week INT DEFAULT 5,
  max_videos_per_week INT DEFAULT 2,
  max_storage_mb INT DEFAULT 500,
  content_generation_enabled BOOLEAN DEFAULT TRUE
);

INSERT INTO plan_limits VALUES
  ('free',     50,   5,  2,   500,  true),
  ('personal', NULL, 20, 7,   5000, true),
  ('pro',      NULL, NULL, NULL, 20000, true)
ON CONFLICT (plan) DO NOTHING;
```

---

## Task 2 — Registration Endpoint

Create: `backend/app/auth/registration.py`

```python
POST /api/auth/register
Body: {
  "email": str,
  "password": str,         # min 12 chars, validated
  "display_name": str,     # min 2 chars
  "referral_source": str   # optional, saved as first memory
}

Response 201: { "message": "Verification email sent", "user_id": str }
Response 400: { "error": "email_taken" | "password_too_short" | "invalid_email" }
Response 429: rate limited (max 5 registrations per IP per hour)
```

### Implementation

```python
async def register(body: RegistrationRequest, request: Request, db: Session):
    # 1. Validate email format
    # 2. Check email not already taken (case-insensitive)
    # 3. Validate password length >= 12
    # 4. Hash password: bcrypt with cost factor 12
    #    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt(rounds=12))
    # 5. Generate email verification token: secrets.token_urlsafe(32)
    # 6. Insert user row (email_verified=False, plan='free')
    # 7. Enqueue verification email (do NOT send inline — use SES queue)
    # 8. If referral_source provided: save as first memory entry
    # 9. Enqueue user provisioning job (Phase 3)
    # 10. Return 201 — never return the user_id in registration (security)
```

**Password hashing:** Use `bcrypt` — never `hashlib`, never MD5, never SHA256 alone.

**Rate limiting:** Use a simple Redis counter or in-memory TTL dict keyed by IP. Fail with 429 after 5 attempts per hour. Add `Retry-After` header.

---

## Task 3 — Email Verification

```python
GET /api/auth/verify-email?token={token}
```

```python
async def verify_email(token: str, db: Session):
    user = db.query(User).filter(
        User.email_verification_token == token,
        User.email_verified == False
    ).first()

    if not user:
        raise HTTPException(400, "Invalid or expired verification link")

    # Token expires after 24 hours
    if user.email_verification_sent_at < datetime.utcnow() - timedelta(hours=24):
        raise HTTPException(400, "Verification link expired — request a new one")

    user.email_verified = True
    user.email_verification_token = None
    db.commit()

    # Return redirect to /onboarding with a short-lived login token
    login_token = create_access_token(user.id)
    return RedirectResponse(f"/onboarding?token={login_token}")
```

```python
POST /api/auth/resend-verification
Body: { "email": str }
# Rate limit: max 3 resends per email per hour
# Silently succeed even if email not found (prevent enumeration)
```

---

## Task 4 — Login Endpoint

```python
POST /api/auth/login
Body: { "email": str, "password": str }

Response 200: { "access_token": str, "token_type": "bearer", "expires_in": 2592000 }
Response 401: { "error": "invalid_credentials" }   # same message for both wrong email and wrong password
Response 403: { "error": "email_not_verified", "message": "Check your inbox to verify your email" }
Response 403: { "error": "account_disabled" }
```

```python
async def login(body: LoginRequest, db: Session):
    # 1. Find user by email (case-insensitive)
    # 2. Verify password with bcrypt.checkpw() — always run checkpw even if user not found
    #    (prevents timing attacks that reveal whether an email is registered)
    # 3. Check email_verified = True
    # 4. Check is_active = True
    # 5. Update last_active_at
    # 6. Return JWT with sub=user_id, exp=30 days
```

JWT payload:
```json
{
  "sub": "user-uuid",
  "email": "user@example.com",
  "plan": "free",
  "is_admin": false,
  "iat": 1234567890,
  "exp": 1234567890
}
```

---

## Task 5 — Password Reset

```python
POST /api/auth/forgot-password
Body: { "email": str }
# Always returns 200 regardless of whether email exists
# If user found: generate reset token, send email, store token + expiry (1 hour)

POST /api/auth/reset-password
Body: { "token": str, "new_password": str }
# Validate token exists + not expired
# Hash new password, clear token, return 200
```

---

## Task 6 — Auth Middleware

Create: `backend/app/core/auth_middleware.py`

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(401, "Invalid token")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(401, "User not found")
    if not user.email_verified:
        raise HTTPException(403, "Email not verified")

    return user

# Inject as dependency on all protected routes:
# async def some_endpoint(current_user: User = Depends(get_current_user)):
```

---

## Task 7 — PostgreSQL Row Level Security

Run after migration:

```sql
-- Enable RLS on all user-data tables
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_research ENABLE ROW LEVEL SECURITY;

-- Policy: users can only see their own rows
-- (app sets app.current_user_id at connection start)
CREATE POLICY user_isolation ON memories
  USING (user_id = current_setting('app.current_user_id')::uuid);

-- Repeat for all tables above
```

In FastAPI, set this at the start of each request:
```python
db.execute(text(f"SET app.current_user_id = '{current_user.id}'"))
```

This is a **defence-in-depth** measure — even if the application has a bug that forgets to filter by user_id, the database will reject the query.

---

## Completion Criteria
- [ ] `POST /api/auth/register` creates user with hashed password
- [ ] Verification email is sent (check SES sandbox or real inbox)
- [ ] `GET /api/auth/verify-email?token=...` activates account and redirects to onboarding
- [ ] `POST /api/auth/login` returns JWT for verified accounts
- [ ] Login returns same error for wrong email and wrong password (no enumeration)
- [ ] Unverified accounts cannot access any protected endpoints
- [ ] RLS enabled on all user-data tables
- [ ] Rate limiting blocks 6th registration attempt from same IP
- [ ] Password reset flow works end-to-end
