/**
 * Private Internet — PrivateInternetStack
 *
 * THIS STACK IS NOT DEPLOYED. Production runs on EC2 + systemd.
 * See infra/README.md for full context and pre-deploy checklist.
 *
 * Resources implemented (Tasks 2–12 from PHASE1_CDK_INFRASTRUCTURE.md):
 *   Task 2  — VPC (2 AZs, 1 NAT, public/private/isolated subnets)
 *   Task 3  — RDS PostgreSQL 16 t3.small + RDS Proxy + db secret
 *   Task 4  — S3 content bucket (private, lifecycle rules)
 *   Task 5  — CloudFront distribution (S3 default + ALB /api/*)
 *   Task 6  — ACM certificate + Route 53 A record
 *   Task 7  — ECS Fargate cluster + ALB (ApplicationLoadBalancedFargateService)
 *             + CPU auto-scaling
 *   Task 8  — ECR repository
 *   Task 9  — SQS content-job queue (+ DLQ) + provisioning queue
 *   Task 10 — EventBridge schedules (topics / posts / videos)
 *   Task 11 — IAM task-role policies (Bedrock, S3, SQS, SES, Polly)
 *   Task 12 — Secrets Manager app secrets (placeholders)
 */

import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

// All AWS service constructs come from the single aws-cdk-lib package (CDK v2).
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as route53Targets from 'aws-cdk-lib/aws-route53-targets';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecsPatterns from 'aws-cdk-lib/aws-ecs-patterns';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as events from 'aws-cdk-lib/aws-events';
import * as eventsTargets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';

// ---------------------------------------------------------------------------
// Stack props — extend cdk.StackProps so callers can pass env / tags etc.
// ---------------------------------------------------------------------------
export interface PrivateInternetStackProps extends cdk.StackProps {
  /**
   * The apex domain to register the certificate and Route 53 record on.
   * Defaults to 'adel-intelligence.com' (current production domain).
   * Override via cdk.json context key "domainName" or --context on the CLI.
   *
   * NOTE: The plan used the fictional 'private.internet'. We always default to
   * the real domain so that this stack can be deployed against the actual
   * Route 53 hosted zone without manual edits.
   */
  readonly domainName: string;
}

// ---------------------------------------------------------------------------
// Stack
// ---------------------------------------------------------------------------
export class PrivateInternetStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: PrivateInternetStackProps) {
    super(scope, id, props);

    const { domainName } = props;

    // -----------------------------------------------------------------------
    // Task 2 — VPC
    //
    // Three subnet tiers:
    //   Public   — NAT gateway, ALB
    //   Private  — ECS Fargate tasks (outbound via NAT)
    //   Isolated — RDS (no internet access at all)
    // -----------------------------------------------------------------------
    const vpc = new ec2.Vpc(this, 'PrivateInternetVpc', {
      maxAzs: 2,
      natGateways: 1, // single NAT is fine at this scale; use 2 when HA matters
      subnetConfiguration: [
        {
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
        {
          name: 'Isolated',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    // -----------------------------------------------------------------------
    // Task 12 — Secrets Manager (created early; referenced by Task 3 & 7)
    //
    // IMPORTANT: The placeholder values below ('REPLACE_BEFORE_DEPLOY') MUST be
    // replaced with real values via the AWS Console or CLI before running
    // `cdk deploy`. Never commit real secrets to this file.
    // -----------------------------------------------------------------------
    const appSecrets = new secretsmanager.Secret(this, 'AppSecrets', {
      secretName: 'private-internet/app',
      description: 'Private Internet application secrets — fill before deploying',
      secretObjectValue: {
        jwt_secret: cdk.SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
        stripe_secret: cdk.SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
        stripe_webhook_secret: cdk.SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
        gemini_api_key: cdk.SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
        internal_secret: cdk.SecretValue.unsafePlainText('REPLACE_BEFORE_DEPLOY'),
      },
    });

    // -----------------------------------------------------------------------
    // Task 3 — RDS PostgreSQL 16 (t3.small, isolated subnets)
    // -----------------------------------------------------------------------
    const dbSecret = new secretsmanager.Secret(this, 'DbSecret', {
      secretName: 'private-internet/db',
      description: 'RDS credentials for private_internet database',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: 'piuser' }),
        generateStringKey: 'password',
        excludePunctuation: true,
      },
    });

    const db = new rds.DatabaseInstance(this, 'Database', {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.SMALL),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      credentials: rds.Credentials.fromSecret(dbSecret),
      databaseName: 'private_internet',
      backupRetention: cdk.Duration.days(7),
      deletionProtection: true,
      storageEncrypted: true,
      multiAz: false, // enable when paying users require HA
    });

    // RDS Proxy — connection pooling for ECS's many short-lived connections
    const dbProxy = new rds.DatabaseProxy(this, 'DbProxy', {
      proxyTarget: rds.ProxyTarget.fromInstance(db),
      secrets: [dbSecret],
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      dbProxyName: 'private-internet-proxy',
      requireTLS: true,
    });

    // -----------------------------------------------------------------------
    // Task 4 — S3 Content Bucket
    // -----------------------------------------------------------------------
    const contentBucket = new s3.Bucket(this, 'ContentBucket', {
      // Account-scoped name avoids global collision without a random suffix
      bucketName: `private-internet-content-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: false,
      removalPolicy: cdk.RemovalPolicy.RETAIN, // never auto-delete user content
      lifecycleRules: [
        {
          // Videos older than 90 days → Glacier Instant Retrieval (cheaper storage)
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER_INSTANT_RETRIEVAL,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
          prefix: 'videos/',
        },
        {
          // Temporary processing artefacts expire after 1 day
          expiration: cdk.Duration.days(1),
          prefix: 'tmp/',
        },
      ],
    });

    // -----------------------------------------------------------------------
    // Task 8 — ECR Repository (created before CloudFront / ECS so the image
    //           reference is available for the task definition)
    // -----------------------------------------------------------------------
    const appRepo = new ecr.Repository(this, 'AppRepo', {
      repositoryName: 'private-internet-app',
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          // Keep the last 10 images; older ones are deleted automatically
          maxImageCount: 10,
          description: 'Retain last 10 images',
        },
      ],
    });

    // -----------------------------------------------------------------------
    // Task 6 — ACM Certificate + Route 53
    //
    // fromLookup requires the hosted zone to already exist in Route 53.
    // The certificate is provisioned in us-east-1 for CloudFront compatibility
    // (CloudFront only accepts ACM certs in us-east-1). The ALB certificate
    // lives in eu-central-1 (same region as the stack).
    // -----------------------------------------------------------------------
    const zone = route53.HostedZone.fromLookup(this, 'Zone', {
      domainName,
    });

    // CloudFront requires the certificate to be in us-east-1
    const cfCert = new acm.DnsValidatedCertificate(this, 'CloudFrontCert', {
      domainName,
      subjectAlternativeNames: [`*.${domainName}`],
      hostedZone: zone,
      // us-east-1 is required for CloudFront certificates
      region: 'us-east-1',
      validation: acm.CertificateValidation.fromDns(zone),
    });

    // ALB certificate (same region as the stack — eu-central-1)
    const albCert = new acm.Certificate(this, 'AlbCert', {
      domainName,
      subjectAlternativeNames: [`*.${domainName}`],
      validation: acm.CertificateValidation.fromDns(zone),
    });

    // -----------------------------------------------------------------------
    // Task 7 — ECS Fargate Cluster + ALB
    //
    // We use ApplicationLoadBalancedFargateService which wires the cluster,
    // task definition, service, target group, and ALB listener together.
    // The container image is pulled from ECR on every deploy.
    // -----------------------------------------------------------------------
    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc,
      clusterName: 'private-internet',
      containerInsights: true,
    });

    // Task definition: 0.5 vCPU / 1 GiB — matches the current t3.large EC2
    // profile for the API process. Increase if profiling shows pressure.
    const taskDef = new ecs.FargateTaskDefinition(this, 'AppTask', {
      memoryLimitMiB: 1024,
      cpu: 512,
    });

    // Container definition
    taskDef.addContainer('App', {
      image: ecs.ContainerImage.fromEcrRepository(appRepo, 'latest'),
      portMappings: [{ containerPort: 8000 }],
      // Non-secret env vars baked at deploy time
      environment: {
        // App connects to the RDS Proxy endpoint, not the DB instance directly
        DATABASE_URL: `postgresql://piuser@${dbProxy.endpoint}/private_internet`,
        S3_CONTENT_BUCKET: contentBucket.bucketName,
        // CLOUDFRONT_BASE_URL is set below after the distribution is created
        AWS_REGION_TEXT: 'eu-central-1',  // Bedrock Claude, Polly, SES
        AWS_REGION_IMAGES: 'eu-west-1',   // Nova Canvas (image gen) — per app config
        APP_DOMAIN: domainName,
      },
      // Secrets injected from Secrets Manager at container start
      secrets: {
        DB_PASSWORD: ecs.Secret.fromSecretsManager(dbSecret, 'password'),
        JWT_SECRET: ecs.Secret.fromSecretsManager(appSecrets, 'jwt_secret'),
        STRIPE_SECRET: ecs.Secret.fromSecretsManager(appSecrets, 'stripe_secret'),
        STRIPE_WEBHOOK_SECRET: ecs.Secret.fromSecretsManager(
          appSecrets,
          'stripe_webhook_secret',
        ),
        GEMINI_API_KEY: ecs.Secret.fromSecretsManager(appSecrets, 'gemini_api_key'),
        INTERNAL_SECRET: ecs.Secret.fromSecretsManager(appSecrets, 'internal_secret'),
      },
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'private-internet',
        // Log group is auto-created by CloudWatch
      }),
    });

    // Fargate service + ALB (pattern creates the listener, target group, etc.)
    const fargateService = new ecsPatterns.ApplicationLoadBalancedFargateService(
      this,
      'AppService',
      {
        cluster,
        taskDefinition: taskDef,
        desiredCount: 2,
        publicLoadBalancer: true,   // ALB in public subnets; tasks in private subnets
        listenerPort: 443,
        certificate: albCert,
        // Health check path — FastAPI serves /health on the root router
        healthCheckGracePeriod: cdk.Duration.seconds(60),
      },
    );

    // Redirect HTTP → HTTPS on the ALB
    fargateService.loadBalancer.addRedirect({
      sourcePort: 80,
      sourceProtocol: elbv2.ApplicationProtocol.HTTP,
      targetPort: 443,
      targetProtocol: elbv2.ApplicationProtocol.HTTPS,
    });

    // Allow Fargate tasks to talk to RDS Proxy
    dbProxy.connections.allowDefaultPortFrom(
      fargateService.service.connections,
      'ECS Fargate → RDS Proxy',
    );

    // CPU auto-scaling: 2 → 10 tasks, scale out fast, scale in conservatively
    const scaling = fargateService.service.autoScaleTaskCount({ maxCapacity: 10 });
    scaling.scaleOnCpuUtilization('CpuScaling', {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(30),
    });

    // -----------------------------------------------------------------------
    // Task 5 — CloudFront Distribution
    //
    // Default behaviour   → S3 content bucket (static assets, brain uploads)
    // /api/*              → ALB → ECS (API + MCP)
    //
    // NOTE: The existing production CloudFront additionally has /mcp/* and
    // /.well-known/* behaviours pointing to the EC2/ALB. Those are FROZEN
    // (breaking them breaks claude.ai MCP clients and RFC 8414 OAuth discovery).
    // They must be reproduced here identically when this stack is activated.
    // -----------------------------------------------------------------------
    const alb = fargateService.loadBalancer;

    const distribution = new cloudfront.Distribution(this, 'Cdn', {
      defaultBehavior: {
        // S3 origin for static content — served privately via OAC
        origin: origins.S3BucketOrigin.withOriginAccessControl(contentBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      additionalBehaviors: {
        // API traffic — no caching, all HTTP methods
        '/api/*': {
          origin: new origins.LoadBalancerV2Origin(alb, {
            protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
          }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
        },
        // MCP server — FROZEN PATH: do not rename or remove
        // claude.ai and other MCP clients are hard-coded to /mcp/*
        '/mcp/*': {
          origin: new origins.LoadBalancerV2Origin(alb, {
            protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
          }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
        },
        // RFC 8414 OAuth 2.0 Authorization Server Metadata — FROZEN PATH
        '/.well-known/*': {
          origin: new origins.LoadBalancerV2Origin(alb, {
            protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
          }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
        },
      },
      certificate: cfCert,
      domainNames: [domainName, `www.${domainName}`],
      // Enable access logs if you add an S3 logging bucket later
      // logBucket: ...,
    });

    // Now that the distribution exists, add its URL to the container env.
    // CDK tokens resolve to the actual value at deploy time.
    const cfUrlEnvAddition = `https://${distribution.distributionDomainName}`;
    taskDef.findContainer('App')!.addEnvironment(
      'CLOUDFRONT_BASE_URL',
      cfUrlEnvAddition,
    );

    // Route 53 alias record: domainName → CloudFront
    new route53.ARecord(this, 'AppRecord', {
      zone,
      target: route53.RecordTarget.fromAlias(
        new route53Targets.CloudFrontTarget(distribution),
      ),
    });

    // www subdomain → same CloudFront distribution
    new route53.ARecord(this, 'WwwRecord', {
      zone,
      recordName: 'www',
      target: route53.RecordTarget.fromAlias(
        new route53Targets.CloudFrontTarget(distribution),
      ),
    });

    // -----------------------------------------------------------------------
    // Task 9 — SQS Queues
    // -----------------------------------------------------------------------

    // Dead-letter queue for failed content jobs (retained 14 days for inspection)
    const contentJobDLQ = new sqs.Queue(this, 'ContentJobDLQ', {
      queueName: 'private-internet-content-jobs-dlq',
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    // Main content job queue (PULSE/SIGNAL pipeline: topics, posts, videos)
    const contentJobQueue = new sqs.Queue(this, 'ContentJobQueue', {
      queueName: 'private-internet-content-jobs',
      visibilityTimeout: cdk.Duration.minutes(15), // max single-job duration
      retentionPeriod: cdk.Duration.days(1),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      deadLetterQueue: {
        queue: contentJobDLQ,
        maxReceiveCount: 3, // retry 3× before parking in DLQ
      },
    });

    // User provisioning queue (account creation, brain init, SES welcome email)
    const provisioningQueue = new sqs.Queue(this, 'ProvisioningQueue', {
      queueName: 'private-internet-user-provisioning',
      visibilityTimeout: cdk.Duration.seconds(30),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    // -----------------------------------------------------------------------
    // Task 10 — EventBridge Schedules
    //
    // EventBridge sends a JSON payload to the SQS queue; the ECS consumer
    // (currently the agents service on port 8001) polls and dispatches jobs.
    // -----------------------------------------------------------------------

    // Topics refresh — daily at 06:00 UTC
    new events.Rule(this, 'TopicsSchedule', {
      ruleName: 'private-internet-topics-daily',
      description: 'Trigger daily topic refresh for all users',
      schedule: events.Schedule.cron({ hour: '6', minute: '0' }),
      targets: [
        new eventsTargets.SqsQueue(contentJobQueue, {
          message: events.RuleTargetInput.fromObject({ job_type: 'topics' }),
        }),
      ],
    });

    // Posts generation — 08:00 and 20:00 UTC (twice daily)
    new events.Rule(this, 'PostsSchedule', {
      ruleName: 'private-internet-posts-twice-daily',
      description: 'Trigger post generation twice daily for all users',
      schedule: events.Schedule.cron({ hour: '8,20', minute: '0' }),
      targets: [
        new eventsTargets.SqsQueue(contentJobQueue, {
          message: events.RuleTargetInput.fromObject({ job_type: 'posts' }),
        }),
      ],
    });

    // Video generation — 10:00 UTC (once daily, after posts exist)
    new events.Rule(this, 'VideosSchedule', {
      ruleName: 'private-internet-videos-daily',
      description: 'Trigger daily video generation for all users',
      schedule: events.Schedule.cron({ hour: '10', minute: '0' }),
      targets: [
        new eventsTargets.SqsQueue(contentJobQueue, {
          message: events.RuleTargetInput.fromObject({ job_type: 'videos' }),
        }),
      ],
    });

    // -----------------------------------------------------------------------
    // Task 11 — IAM Task Role Permissions
    //
    // The ECS task role is auto-created by the FargateTaskDefinition.
    // We add least-privilege policies on top.
    // -----------------------------------------------------------------------

    // Bedrock: Claude Haiku (text), Nova Canvas (images), Titan Embed v2
    // AmazonBedrockFullAccess is broad but matches the existing production
    // permissions. Tighten to specific model ARNs when you go multi-tenant.
    taskDef.taskRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonBedrockFullAccess'),
    );

    // S3: read/write to the content bucket (brain uploads, generated media)
    contentBucket.grantReadWrite(taskDef.taskRole);

    // SQS: send + consume on both queues
    contentJobQueue.grantSendMessages(taskDef.taskRole);
    contentJobQueue.grantConsumeMessages(taskDef.taskRole);
    provisioningQueue.grantSendMessages(taskDef.taskRole);
    provisioningQueue.grantConsumeMessages(taskDef.taskRole);

    // SES + Polly: attach as an inline policy on the task role.
    // taskDef.taskRole is typed IRole; we attach a named Policy construct instead
    // of calling .addToPolicy() directly (which only exists on Role, not IRole).
    new iam.Policy(this, 'TaskInlinePolicy', {
      statements: [
        // SES: send transactional and notification emails
        new iam.PolicyStatement({
          sid: 'SesEmailSend',
          actions: ['ses:SendEmail', 'ses:SendRawEmail', 'ses:SendTemplatedEmail'],
          // Restrict to verified identities in prod; '*' for initial deployment
          resources: ['*'],
        }),
        // Polly: text-to-speech for brain audio narration
        new iam.PolicyStatement({
          sid: 'PollyTts',
          actions: ['polly:SynthesizeSpeech', 'polly:DescribeVoices'],
          resources: ['*'],
        }),
      ],
      roles: [taskDef.taskRole as iam.Role],
    });

    // Secrets Manager: allow the task to read the app secrets
    appSecrets.grantRead(taskDef.taskRole);
    dbSecret.grantRead(taskDef.taskRole);

    // -----------------------------------------------------------------------
    // Stack Outputs — printed after `cdk deploy` and visible in CloudFormation
    // -----------------------------------------------------------------------
    new cdk.CfnOutput(this, 'CloudFrontUrl', {
      value: `https://${distribution.distributionDomainName}`,
      description: 'CloudFront distribution domain (use domainName alias in DNS)',
    });

    new cdk.CfnOutput(this, 'AlbDnsName', {
      value: fargateService.loadBalancer.loadBalancerDnsName,
      description: 'Application Load Balancer DNS name',
    });

    new cdk.CfnOutput(this, 'EcrRepoUri', {
      value: appRepo.repositoryUri,
      description: 'ECR repository URI — push images here before deploying',
    });

    new cdk.CfnOutput(this, 'DbProxyEndpoint', {
      value: dbProxy.endpoint,
      description: 'RDS Proxy endpoint for DATABASE_URL',
    });

    new cdk.CfnOutput(this, 'ContentBucketName', {
      value: contentBucket.bucketName,
      description: 'S3 content bucket name (S3_CONTENT_BUCKET env var)',
    });

    new cdk.CfnOutput(this, 'ContentJobQueueUrl', {
      value: contentJobQueue.queueUrl,
      description: 'SQS URL for content pipeline jobs',
    });

    new cdk.CfnOutput(this, 'ProvisioningQueueUrl', {
      value: provisioningQueue.queueUrl,
      description: 'SQS URL for user provisioning jobs',
    });
  }
}
