#!/usr/bin/env node
/**
 * Private Internet — CDK App Entry Point
 *
 * THIS STACK IS NOT DEPLOYED.
 * Production currently runs on EC2 + systemd (personal-intelligence-api /
 * personal-intelligence-agents) behind nginx + CloudFront.
 * This is a future migration target only.
 *
 * Usage (when ready to deploy):
 *   1. Fill Secrets Manager values — see infra/README.md
 *   2. Ensure CDK_DEFAULT_ACCOUNT is set to the target AWS account
 *   3. npx cdk bootstrap aws://<account>/eu-central-1
 *   4. npx cdk deploy --context domainName=adel-intelligence.com
 */

import * as cdk from 'aws-cdk-lib';
import { PrivateInternetStack } from '../lib/private-internet-stack';

const app = new cdk.App();

// domainName can be overridden via --context domainName=... on the CLI.
// Default matches the current production domain.
const domainName = app.node.tryGetContext('domainName') ?? 'adel-intelligence.com';

new PrivateInternetStack(app, 'PrivateInternetStack', {
  domainName,
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    // Region for compute / text inference (Bedrock Claude, Polly, SES)
    region: 'eu-central-1',
  },
  // Human-readable description shown in the CloudFormation console
  description: 'Private Internet — VPC, ECS Fargate, RDS, S3, CloudFront, SQS (future migration target)',
});

app.synth();
