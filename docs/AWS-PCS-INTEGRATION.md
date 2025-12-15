# AWS Parallel Computing Service (PCS) Integration

This fork of Slurm-web adds native support for AWS Parallel Computing Service (PCS) JWT authentication.

## What's New

This integration adds a new `pcs` JWT mode that allows Slurm-web to authenticate with AWS PCS clusters using signing keys stored in AWS Secrets Manager.

### Key Features

- **Native PCS Support**: Automatic JWT token generation with POSIX user identity claims required by AWS PCS
- **Secure Key Management**: JWT signing keys are retrieved from AWS Secrets Manager (never stored on disk)
- **Short-lived Tokens**: Fresh tokens generated for each request (typically 5-minute lifespan)
- **Separation of Concerns**: UI JWT and PCS JWT are completely separate - PCS tokens never leave the agent
- **Zero Configuration Changes to UI**: Only the agent configuration needs to be modified

## Why This Fork?

AWS PCS uses a different JWT authentication model than standard Slurm installations:

- **Standard Slurm**: Uses a shared JWT key file with simple username claims
- **AWS PCS**: Requires JWT tokens with full POSIX identity claims (uid, gid, gecos, etc.) signed with a key from AWS Secrets Manager

This fork bridges that gap by adding PCS-specific authentication at the agent → slurmrestd layer, while keeping the UI authentication unchanged.

## Architecture

```
Browser
  ↓ (UI JWT / session / anonymous)
Gateway
  ↓ (NO CHANGE)
Agent
  ↓ (PCS Scheduler JWT with POSIX claims)
slurmrestd (AWS PCS)
```

**Critical Design Principle**: The two JWT tokens never mix:
- **UI JWT**: For browser authentication (can be anonymous or user-specific)
- **PCS JWT**: Only for agent→slurmrestd, contains full POSIX claims

## Quick Start

### 1. Prerequisites

```bash
# Install boto3 for AWS SDK
pip install boto3

# Configure AWS credentials (if not using IAM role)
aws configure
```

### 2. Configuration

Add to `/etc/slurm-web/agent.ini`:

```ini
[slurmrestd]
uri = http://10.0.1.100:6820  # Your PCS slurmrestd endpoint
auth = jwt
jwt_mode = pcs                 # Enable PCS mode
jwt_user = slurm-web
jwt_lifespan = 300

# AWS PCS specific settings
pcs_secret_id = arn:aws:secretsmanager:us-east-1:123456789012:secret:pcs-cluster-key-abc123
pcs_region = us-east-1
pcs_uid = 0                    # Root access
pcs_gid = 0
```

### 3. Start the Agent

```bash
slurm-web-agent
```

Look for successful initialization in logs:
```
INFO - PCS JWT provider initialized for secret arn:aws:...
INFO - Successfully retrieved signing key from Secrets Manager
INFO - AWS PCS JWT authentication mode initialized
```

## Files Modified

### New Files

- `slurmweb/slurmrestd/pcs.py` - PCS JWT provider implementation
- `docs/examples/agent-pcs.ini` - Example PCS configuration
- `docs/modules/install/pages/aws-pcs.adoc` - Complete PCS setup guide
- `docs/AWS-PCS-INTEGRATION.md` - This file

### Modified Files

- `slurmweb/slurmrestd/auth.py` - Added PCS mode support to authentication
- `slurmweb/apps/agent.py` - Pass PCS parameters to authenticator
- `conf/vendor/agent.yml` - Added PCS configuration schema

## Configuration Reference

### Required Parameters (PCS mode)

- `jwt_mode = pcs` - Enable PCS JWT authentication
- `pcs_secret_id` - AWS Secrets Manager secret ARN for JWT key
- `pcs_region` - AWS region where secret is stored

### Optional Parameters (PCS mode)

- `pcs_uid` - POSIX user ID (default: 0)
- `pcs_gid` - POSIX group ID (default: 0)
- `pcs_gids` - Additional group IDs (default: [pcs_gid])
- `pcs_gecos` - User GECOS field (default: "Slurm Web Agent")
- `pcs_home_dir` - Home directory (default: "/")
- `pcs_shell` - Shell (default: "/sbin/nologin")

## AWS IAM Permissions

The agent needs permission to read the JWT signing key:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:pcs-*"
    }
  ]
}
```

## Security Considerations

✅ **What This Does Right**

- Tokens are short-lived (5 minutes recommended)
- Tokens are generated fresh for each slurmrestd request
- PCS JWT never exposed to browser or UI
- Signing key never written to disk
- Clean separation between UI JWT and PCS JWT

⚠️ **Important Notes**

- Default UID/GID is 0 (root) - has full Slurm access
- Signing key is cached in memory after first fetch
- AWS credentials needed (IAM role recommended)

## Troubleshooting

### boto3 not installed

```bash
pip install boto3
```

### AWS credentials not found

```bash
# For EC2: Attach IAM role with Secrets Manager permissions
# For local: Configure AWS CLI
aws configure
```

### "Missing pcs_secret_id in configuration"

Add `pcs_secret_id` parameter to your `[slurmrestd]` section.

### Authentication failures

1. Check slurmrestd endpoint is reachable
2. Verify secret ARN is correct
3. Confirm AWS credentials have proper permissions
4. Check token lifespan isn't too short

## Documentation

- **Complete Setup Guide**: `docs/modules/install/pages/aws-pcs.adoc`
- **Example Configuration**: `docs/examples/agent-pcs.ini`
- **AWS PCS Documentation**: https://docs.aws.amazon.com/pcs/latest/userguide/authenticating-with-slurm-rest-api.html

## Compatibility

- **Slurm Version**: Requires Slurm 25.05+ (AWS PCS requirement)
- **Python Version**: Compatible with Python 3.6+
- **AWS SDK**: Requires boto3 >= 1.20.0
- **Upstream Compatibility**: All changes are additive - standard JWT modes still work

## Upstream Considerations

This is a fork-specific feature designed for AWS PCS. Key points:

- PCS mode is isolated in its own module (`pcs.py`)
- Existing JWT modes (`auto`, `static`) are unchanged
- No breaking changes to upstream behavior
- Can be upstreamed if there's interest

## Contributing

If you find issues with PCS integration:

1. Check the troubleshooting guide
2. Review logs with debug mode enabled
3. Verify AWS permissions and credentials
4. Open an issue with full error details

## License

This integration maintains the same license as the upstream Slurm-web project (MIT License).

## Credits

Implementation based on:
- [AWS PCS JWT Authentication Guide](https://docs.aws.amazon.com/pcs/latest/userguide/authenticating-with-slurm-rest-api.html)
- Engineering discussion and architecture guidance
- Slurm-web upstream project by Rackslab
