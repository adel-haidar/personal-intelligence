# Private Internet — CDK Infrastructure

> **THIS STACK IS NOT DEPLOYED.**
> Production currently runs on EC2 + systemd (`personal-intelligence-api` /
> `personal-intelligence-agents`) behind nginx and CloudFront, managed by
> GitHub Actions SSM. This CDK project is a future migration target only.
> Do not run `cdk deploy` or `cdk bootstrap` without explicit sign-off.

---

## What this is

A CDK v2 TypeScript app (`PrivateInternetStack`) that would replace the current
hand-configured EC2 setup with reproducible, version-controlled AWS infrastructure.
One `cdk deploy` would create the entire stack from scratch in `eu-central-1`.

### Resources defined

| Task | Resource |
|------|----------|
| 2 | VPC — 2 AZs, 1 NAT gateway, public / private / isolated subnets |
| 3 | RDS PostgreSQL 16 t3.small (isolated subnets) + RDS Proxy + db secret |
| 4 | S3 content bucket (private, lifecycle rules: videos → Glacier after 90d, tmp → delete after 1d) |
| 5 | CloudFront distribution — S3 default + ALB `/api/*`, `/mcp/*`, `/.well-known/*` |
| 6 | ACM certificate (us-east-1 for CloudFront, eu-central-1 for ALB) + Route 53 A record |
| 7 | ECS Fargate cluster + ALB (`ApplicationLoadBalancedFargateService`) + CPU auto-scaling (2→10 tasks) |
| 8 | ECR repository (`private-internet-app`, last 10 images retained) |
| 9 | SQS content-job queue + DLQ + user provisioning queue |
| 10 | EventBridge schedules (topics 06:00 UTC, posts 08:00 & 20:00 UTC, videos 10:00 UTC) |
| 11 | IAM task-role policies: Bedrock, S3, SQS, SES, Polly, Secrets Manager |
| 12 | Secrets Manager `private-internet/app` (placeholders) + `private-internet/db` (auto-generated) |

---

## Differences from the plan document

The plan (`project-plan/multi-user/extracted/PHASE1_CDK_INFRASTRUCTURE.md`) contained
several items that were adjusted:

| Plan | This scaffold |
|------|---------------|
| CDK v1 `@aws-cdk/aws-*` packages | CDK v2 single package `aws-cdk-lib` |
| Domain `private.internet` (fictional) | Default `adel-intelligence.com` (real, via `domainName` context key) |
| `S3_BUCKET` env var | `S3_CONTENT_BUCKET` (matches `config.py` / app code) |
| No `/mcp/*` or `/.well-known/*` behaviours | Both added — FROZEN paths, required for claude.ai MCP + RFC 8414 |
| Single ACM cert (region unspecified) | Two certs: us-east-1 for CloudFront, eu-central-1 for ALB |
| `S3Origin` (deprecated) | `S3BucketOrigin.withOriginAccessControl` (CDK v2 recommended) |

---

## Pre-deploy checklist (manual steps required before `cdk deploy` can succeed)

Complete **all** of these steps before touching `cdk deploy`:

1. **Fill Secrets Manager values**
   The `private-internet/app` secret is created with `REPLACE_BEFORE_DEPLOY`
   placeholders. Before deploying ECS tasks, update via AWS CLI:
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id private-internet/app \
     --secret-string '{
       "jwt_secret": "<generate with: openssl rand -hex 32>",
       "stripe_secret": "sk_live_...",
       "stripe_webhook_secret": "whsec_...",
       "gemini_api_key": "AIza...",
       "internal_secret": "<generate with: openssl rand -hex 32>"
     }'
   ```

2. **Request SES production access**
   By default SES is in sandbox mode (can only send to verified addresses).
   Submit a production access request in the AWS console before going live.
   Also verify the sending domain: `aws ses verify-domain-identity --domain adel-intelligence.com`

3. **Set the `domainName` context** (if not using the default)
   ```bash
   npx cdk deploy --context domainName=adel-intelligence.com
   ```
   Or edit `cdk.json` → `context.domainName`.

4. **Ensure the Route 53 hosted zone exists**
   The stack calls `HostedZone.fromLookup` which requires an existing hosted
   zone in the target account. If the domain is registered elsewhere, delegate
   the NS records to Route 53 first.

5. **CDK bootstrap the target account/region**
   ```bash
   npx cdk bootstrap aws://<ACCOUNT_ID>/eu-central-1
   # Also bootstrap us-east-1 for the cross-region CloudFront certificate
   npx cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
   ```

6. **Push an initial Docker image to ECR**
   The ECS service will fail to start if no image exists in the ECR repo.
   After `cdk deploy` creates the repo, build and push:
   ```bash
   aws ecr get-login-password --region eu-central-1 | \
     docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.eu-central-1.amazonaws.com
   docker build -t private-internet-app .
   docker tag private-internet-app:latest \
     <ACCOUNT_ID>.dkr.ecr.eu-central-1.amazonaws.com/private-internet-app:latest
   docker push <ACCOUNT_ID>.dkr.ecr.eu-central-1.amazonaws.com/private-internet-app:latest
   ```

7. **Run database migrations**
   After the ECS service is up, run migrations via the EC2 bastion or a one-off
   ECS task:
   ```bash
   # Example: run via existing EC2 bastion (current production)
   ssh ec2-user@<EC2_IP>
   psql "host=<proxy-endpoint> dbname=private_internet user=piuser" \
     < migrations/0005_multi_tenancy.sql
   ```

8. **Verify CloudFront behaviour paths before cutting over**
   Confirm `/mcp/*` and `/.well-known/*` both proxy correctly to the ALB. These
   are frozen paths — do not rename them.

9. **Cut over DNS** (last step)
   Update Route 53 to alias the domain to the new CloudFront distribution only
   after all of the above are verified. The existing EC2 stays live until then.

---

## Local validation (no deploy)

```bash
cd infra
npm install
npm run build      # tsc compile
npx cdk synth      # generate CloudFormation template (no AWS calls except HostedZone lookup)
```

`cdk synth` will fail if `CDK_DEFAULT_ACCOUNT` is unset (Route 53 lookup needs it).
Set it to any placeholder to check TypeScript output:
```bash
CDK_DEFAULT_ACCOUNT=123456789012 npx cdk synth
```

---

## Production environment variable mapping

The Fargate task environment mirrors the current EC2 environment variables:

| CDK env key | Current EC2 env key | Notes |
|-------------|--------------------|-|
| `DATABASE_URL` | `DATABASE_URL` | Points to RDS Proxy endpoint, not instance |
| `S3_CONTENT_BUCKET` | `S3_CONTENT_BUCKET` | Content bucket name |
| `CLOUDFRONT_BASE_URL` | `CLOUDFRONT_BASE_URL` | CloudFront distribution URL |
| `AWS_REGION_TEXT` | `AWS_REGION` | eu-central-1 (Bedrock text, Polly, SES) |
| `AWS_REGION_IMAGES` | `AWS_REGION_IMAGES` | eu-west-1 (Nova Canvas image gen) |
| `APP_DOMAIN` | `APP_DOMAIN` | Apex domain, used for OAuth issuer URL |
| `JWT_SECRET` | `JWT_SECRET` | From Secrets Manager |
| `INTERNAL_SECRET` | `INTERNAL_SECRET` | From Secrets Manager |
| `STRIPE_SECRET` | `STRIPE_SECRET` | From Secrets Manager |
| `GEMINI_API_KEY` | `GEMINI_API_KEY` | From Secrets Manager |
