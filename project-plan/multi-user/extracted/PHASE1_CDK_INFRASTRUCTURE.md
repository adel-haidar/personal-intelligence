# PHASE 1 — Infrastructure as Code (AWS CDK)
## Agent: Claude Code
## Depends on: nothing — run first

---

## Goal
Replace the manually configured EC2 setup with reproducible, version-controlled AWS infrastructure using CDK (TypeScript). One `cdk deploy` should bring up the entire stack from scratch. The existing EC2 stays running until the new stack is verified — then cut over.

---

## Task 1 — CDK Project Setup

Create: `infra/` at repo root

```bash
cd infra
npx cdk init app --language typescript
npm install @aws-cdk/aws-ec2 @aws-cdk/aws-ecs @aws-cdk/aws-rds \
  @aws-cdk/aws-s3 @aws-cdk/aws-cloudfront @aws-cdk/aws-ses \
  @aws-cdk/aws-sqs @aws-cdk/aws-events @aws-cdk/aws-route53 \
  @aws-cdk/aws-certificatemanager @aws-cdk/aws-elasticloadbalancingv2 \
  @aws-cdk/aws-ecs-patterns @aws-cdk/aws-secretsmanager \
  @aws-cdk/aws-applicationautoscaling
```

Stack name: `PrivateInternetStack`
Region: `eu-central-1`
Account: from env `CDK_DEFAULT_ACCOUNT`

---

## Task 2 — VPC

```typescript
const vpc = new ec2.Vpc(this, 'PrivateInternetVpc', {
  maxAzs: 2,
  natGateways: 1,          // one NAT gateway — two is redundant at this scale
  subnetConfiguration: [
    { name: 'Public',  subnetType: ec2.SubnetType.PUBLIC,           cidrMask: 24 },
    { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
    { name: 'Isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
  ],
})
```

App runs in Private subnets.
RDS runs in Isolated subnets (no internet access at all).
NAT gateway in Public subnet for outbound calls (Bedrock, Stripe, etc).

---

## Task 3 — RDS PostgreSQL

```typescript
const dbSecret = new secretsmanager.Secret(this, 'DbSecret', {
  secretName: 'private-internet/db',
  generateSecretString: {
    secretStringTemplate: JSON.stringify({ username: 'piuser' }),
    generateStringKey: 'password',
    excludePunctuation: true,
  },
})

const db = new rds.DatabaseInstance(this, 'Database', {
  engine: rds.DatabaseInstanceEngine.postgres({
    version: rds.PostgresEngineVersion.VER_16,
  }),
  instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.SMALL),
  vpc,
  vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
  credentials: rds.Credentials.fromSecret(dbSecret),
  databaseName: 'private_internet',
  backupRetention: Duration.days(7),
  deletionProtection: true,
  storageEncrypted: true,
  multiAz: false,           // enable when you have paying users
})
```

**RDS Proxy** (connection pooling — critical for Lambda/ECS with many short-lived connections):
```typescript
const proxy = new rds.DatabaseProxy(this, 'DbProxy', {
  proxyTarget: rds.ProxyTarget.fromInstance(db),
  secrets: [dbSecret],
  vpc,
  dbProxyName: 'private-internet-proxy',
  requireTLS: true,
})
```

App connects to `proxy.endpoint`, not `db.instanceEndpoint`.

---

## Task 4 — S3 Bucket

```typescript
const contentBucket = new s3.Bucket(this, 'ContentBucket', {
  bucketName: `private-internet-content-${this.account}`,
  encryption: s3.BucketEncryption.S3_MANAGED,
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
  versioned: false,
  lifecycleRules: [
    {
      // Move videos older than 90 days to Glacier Instant
      transitions: [{
        storageClass: s3.StorageClass.GLACIER_INSTANT_RETRIEVAL,
        transitionAfter: Duration.days(90),
        prefix: '*/videos/',
      }],
    },
    {
      // Delete temp processing files after 1 day
      expiration: Duration.days(1),
      prefix: '*/tmp/',
    },
  ],
})
```

---

## Task 5 — CloudFront Distribution

```typescript
const distribution = new cloudfront.Distribution(this, 'Cdn', {
  defaultBehavior: {
    origin: new origins.S3Origin(contentBucket),
    viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
    cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
  },
  additionalBehaviors: {
    '/api/*': {
      origin: new origins.LoadBalancerV2Origin(alb),  // see Task 7
      viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
      allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
    },
  },
  certificate: acmCert,     // see Task 6
  domainNames: ['private.internet', '*.private.internet'],
})
```

---

## Task 6 — ACM Certificate & Route 53

```typescript
const zone = route53.HostedZone.fromLookup(this, 'Zone', {
  domainName: 'private.internet',
})

const cert = new acm.Certificate(this, 'Cert', {
  domainName: 'private.internet',
  subjectAlternativeNames: ['*.private.internet'],
  validation: acm.CertificateValidation.fromDns(zone),
})
```

DNS records:
```typescript
new route53.ARecord(this, 'AppRecord', {
  zone,
  target: route53.RecordTarget.fromAlias(new targets.CloudFrontTarget(distribution)),
})
```

---

## Task 7 — ECS Fargate + Application Load Balancer

```typescript
const cluster = new ecs.Cluster(this, 'Cluster', { vpc })

const taskDef = new ecs.FargateTaskDefinition(this, 'AppTask', {
  memoryLimitMiB: 1024,
  cpu: 512,
})

taskDef.addContainer('App', {
  image: ecs.ContainerImage.fromEcrRepository(appRepo),  // see Task 8
  portMappings: [{ containerPort: 8000 }],
  environment: {
    DATABASE_URL: `postgresql://piuser@${proxy.endpoint}/private_internet`,
    S3_BUCKET: contentBucket.bucketName,
    CLOUDFRONT_URL: `https://${distribution.distributionDomainName}`,
    AWS_REGION_TEXT: 'eu-central-1',
    AWS_REGION_IMAGES: 'eu-west-1',
  },
  secrets: {
    DB_PASSWORD: ecs.Secret.fromSecretsManager(dbSecret, 'password'),
    JWT_SECRET: ecs.Secret.fromSecretsManager(appSecrets, 'jwt_secret'),
    STRIPE_SECRET: ecs.Secret.fromSecretsManager(appSecrets, 'stripe_secret'),
    GEMINI_API_KEY: ecs.Secret.fromSecretsManager(appSecrets, 'gemini_api_key'),
    INTERNAL_SECRET: ecs.Secret.fromSecretsManager(appSecrets, 'internal_secret'),
  },
  logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'private-internet' }),
})

const fargateService = new ecsPatterns.ApplicationLoadBalancedFargateService(
  this, 'AppService', {
    cluster,
    taskDefinition: taskDef,
    desiredCount: 2,
    publicLoadBalancer: true,
    listenerPort: 443,
    certificate: cert,
  }
)

// Auto-scaling
const scaling = fargateService.service.autoScaleTaskCount({ maxCapacity: 10 })
scaling.scaleOnCpuUtilization('CpuScaling', {
  targetUtilizationPercent: 70,
  scaleInCooldown: Duration.seconds(60),
  scaleOutCooldown: Duration.seconds(30),
})
```

---

## Task 8 — ECR Repository + GitHub Actions CI/CD

```typescript
const appRepo = new ecr.Repository(this, 'AppRepo', {
  repositoryName: 'private-internet-app',
  lifecycleRules: [{ maxImageCount: 10 }],   // keep last 10 images only
})
```

Update `.github/workflows/deploy.yml`:
```yaml
- name: Build and push to ECR
  run: |
    aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URI
    docker build -t $ECR_URI:$GITHUB_SHA .
    docker push $ECR_URI:$GITHUB_SHA

- name: Deploy to ECS
  run: |
    aws ecs update-service \
      --cluster private-internet \
      --service AppService \
      --force-new-deployment
```

---

## Task 9 — SQS Queues

```typescript
const contentJobQueue = new sqs.Queue(this, 'ContentJobQueue', {
  queueName: 'private-internet-content-jobs',
  visibilityTimeout: Duration.minutes(15),   // max job duration
  retentionPeriod: Duration.days(1),
  deadLetterQueue: {
    queue: new sqs.Queue(this, 'ContentJobDLQ', { retentionPeriod: Duration.days(14) }),
    maxReceiveCount: 3,
  },
})

const provisioningQueue = new sqs.Queue(this, 'ProvisioningQueue', {
  queueName: 'private-internet-user-provisioning',
  visibilityTimeout: Duration.seconds(30),
})
```

---

## Task 10 — EventBridge Scheduler

```typescript
// Topics job — daily 6am UTC
new events.Rule(this, 'TopicsSchedule', {
  schedule: events.Schedule.cron({ hour: '6', minute: '0' }),
  targets: [new targets.SqsQueue(contentJobQueue, {
    message: events.RuleTargetInput.fromObject({ job_type: 'topics' }),
  })],
})

// Posts — 8am and 8pm UTC
new events.Rule(this, 'PostsSchedule', {
  schedule: events.Schedule.cron({ hour: '8,20', minute: '0' }),
  targets: [new targets.SqsQueue(contentJobQueue, {
    message: events.RuleTargetInput.fromObject({ job_type: 'posts' }),
  })],
})

// Videos — 10am UTC
new events.Rule(this, 'VideosSchedule', {
  schedule: events.Schedule.cron({ hour: '10', minute: '0' }),
  targets: [new targets.SqsQueue(contentJobQueue, {
    message: events.RuleTargetInput.fromObject({ job_type: 'videos' }),
  })],
})
```

---

## Task 11 — IAM Roles

ECS task role permissions:
```typescript
taskDef.taskRole.addManagedPolicy(
  iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonBedrockFullAccess')
)
contentBucket.grantReadWrite(taskDef.taskRole)
contentJobQueue.grantSendMessages(taskDef.taskRole)
contentJobQueue.grantConsumeMessages(taskDef.taskRole)
provisioningQueue.grantSendMessages(taskDef.taskRole)
provisioningQueue.grantConsumeMessages(taskDef.taskRole)

// SES send permission
taskDef.taskRole.addToPolicy(new iam.PolicyStatement({
  actions: ['ses:SendEmail', 'ses:SendRawEmail', 'ses:SendTemplatedEmail'],
  resources: ['*'],
}))

// Polly
taskDef.taskRole.addToPolicy(new iam.PolicyStatement({
  actions: ['polly:SynthesizeSpeech', 'polly:DescribeVoices'],
  resources: ['*'],
}))
```

---

## Task 12 — Secrets Manager

Create a single app secrets object:
```typescript
const appSecrets = new secretsmanager.Secret(this, 'AppSecrets', {
  secretName: 'private-internet/app',
  secretObjectValue: {
    jwt_secret: SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
    stripe_secret: SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
    stripe_webhook_secret: SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
    gemini_api_key: SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
    internal_secret: SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
  },
})
```

Fill actual values via AWS Console or CLI before first deploy. Never commit secrets to git.

---

## Completion Criteria
- [ ] `cdk synth` produces valid CloudFormation with no errors
- [ ] `cdk deploy` creates all resources in eu-central-1
- [ ] ECS service shows 2 running tasks
- [ ] RDS accessible from ECS tasks only (not from public internet)
- [ ] S3 bucket not publicly accessible
- [ ] CloudFront serves content via HTTPS
- [ ] SSL certificate valid for `private.internet` and `*.private.internet`
- [ ] GitHub Actions pushes new images and triggers ECS redeploy
- [ ] All secrets in Secrets Manager, none in environment variables or code
