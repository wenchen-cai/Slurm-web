# Testing AWS PCS Integration

This document explains how to test the AWS PCS JWT authentication integration.

## Running Tests

### Prerequisites

Install test dependencies:

```bash
# Install Slurm-web with test dependencies
pip install -e ".[tests]"

# Install agent dependencies (includes boto3)
pip install -e ".[agent]"
```

### Run All Tests

```bash
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=slurmweb --cov-report=html
```

### Run PCS-Specific Tests

```bash
# Run only PCS tests
python -m pytest slurmweb/tests/slurmrestd/test_pcs.py

# Run with verbose output
python -m pytest slurmweb/tests/slurmrestd/test_pcs.py -v

# Run specific test class
python -m pytest slurmweb/tests/slurmrestd/test_pcs.py::TestPCSJwtProvider

# Run specific test method
python -m pytest slurmweb/tests/slurmrestd/test_pcs.py::TestPCSJwtProvider::test_generate_token
```

### Run Authentication Tests

```bash
# Run all authentication tests (including PCS)
python -m pytest slurmweb/tests/slurmrestd/test_auth.py slurmweb/tests/slurmrestd/test_pcs.py
```

## Test Coverage

The PCS integration includes comprehensive tests for:

### Unit Tests (`test_pcs.py`)

1. **Provider Initialization**
   - Test PCS JWT provider initialization
   - Verify configuration parameters

2. **Signing Key Management**
   - Fetch signing key from AWS Secrets Manager
   - Handle AWS access errors (AccessDenied, etc.)
   - Key caching and refresh
   - Key version tracking

3. **Token Generation**
   - Generate JWT with POSIX claims
   - Verify token expiration times
   - Validate token payload structure
   - Test with different UID/GID configurations

4. **Error Handling**
   - Missing boto3 dependency
   - AWS credential errors
   - Invalid configuration

### Integration Tests (`test_pcs.py`)

1. **Authentifier Integration**
   - PCS mode initialization in SlurmrestdAuthentifier
   - Configuration validation
   - Header generation with PCS tokens
   - Fresh token generation for each request

## Manual Testing

### Setup Test Environment

1. **Create test AWS resources** (optional - tests use mocks):

```bash
# This is only needed if you want to test with real AWS
aws secretsmanager create-secret \
    --name test-slurm-web-pcs-key \
    --secret-string $(python -c "import secrets; print(secrets.token_hex(32))")
```

2. **Create test configuration**:

```ini
# test-agent.ini
[service]
cluster = test-cluster
port = 5012

[slurmrestd]
uri = http://localhost:6820
auth = jwt
jwt_mode = pcs
jwt_user = test-user
jwt_lifespan = 300

pcs_secret_id = arn:aws:secretsmanager:us-east-1:123456789012:secret:test-key
pcs_region = us-east-1
pcs_uid = 1000
pcs_gid = 1000
```

3. **Test configuration loading**:

```bash
slurm-web-show-conf --agent test-agent.ini
```

### Test with Mock AWS

The tests use `unittest.mock` to mock AWS services, so you don't need real AWS resources:

```python
# Example: Test token generation without AWS
import unittest
from unittest.mock import patch, MagicMock
import base64

class TestPCSManual(unittest.TestCase):
    @patch('slurmweb.slurmrestd.pcs.boto3')
    def test_manual(self, mock_boto3):
        from slurmweb.slurmrestd.pcs import PCSJwtProvider
        
        # Mock AWS response
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        test_key = b"test_secret_key_32_bytes_long!!!"
        mock_client.get_secret_value.return_value = {
            'SecretString': base64.b64encode(test_key).decode('utf-8'),
            'VersionId': 'test-version'
        }
        
        # Create provider
        provider = PCSJwtProvider(
            secret_id="arn:aws:secretsmanager:us-east-1:123:secret:test",
            region="us-east-1",
            username="test-user",
            uid=1000,
            gid=1000,
        )
        
        # Generate token
        token = provider.generate_token()
        print(f"Generated token: {token[:50]}...")
```

## CI/CD Integration

### GitHub Actions

```yaml
name: Test PCS Integration

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      
      - name: Install dependencies
        run: |
          pip install -e ".[tests,agent]"
      
      - name: Run PCS tests
        run: |
          pytest slurmweb/tests/slurmrestd/test_pcs.py -v
      
      - name: Run all tests with coverage
        run: |
          pytest --cov=slurmweb --cov-report=xml
```

## Debugging Tests

### Enable Debug Output

```bash
# Show print statements
pytest -s slurmweb/tests/slurmrestd/test_pcs.py

# Show logging output
pytest --log-cli-level=DEBUG slurmweb/tests/slurmrestd/test_pcs.py
```

### Test Individual Components

```python
# Test JWT encoding directly
import jwt
import time

payload = {
    'exp': int(time.time() + 300),
    'iat': int(time.time()),
    'sun': 'test-user',
    'uid': 1000,
    'gid': 1000,
    'id': {
        'gecos': 'Test User',
        'dir': '/home/test',
        'shell': '/bin/bash',
        'gids': [1000, 100]
    }
}

key = b"test_secret_key"
token = jwt.encode(payload, key, algorithm='HS256')
print(f"Token: {token}")

# Decode and verify
decoded = jwt.decode(token, key, algorithms=['HS256'])
print(f"Decoded: {decoded}")
```

## Test Scenarios

### Scenario 1: Basic Token Generation

```bash
pytest slurmweb/tests/slurmrestd/test_pcs.py::TestPCSJwtProvider::test_generate_token -v
```

Expected: Token generated with correct POSIX claims.

### Scenario 2: AWS Access Denied

```bash
pytest slurmweb/tests/slurmrestd/test_pcs.py::TestPCSJwtProvider::test_fetch_signing_key_access_denied -v
```

Expected: Proper error handling for AWS permission errors.

### Scenario 3: Key Rotation

```bash
pytest slurmweb/tests/slurmrestd/test_pcs.py::TestPCSJwtProvider::test_refresh_key -v
```

Expected: Provider fetches new key after rotation.

### Scenario 4: Configuration Validation

```bash
pytest slurmweb/tests/slurmrestd/test_pcs.py::TestPCSAuthentifierIntegration::test_pcs_mode_missing_secret_id -v
pytest slurmweb/tests/slurmrestd/test_pcs.py::TestPCSAuthentifierIntegration::test_pcs_mode_missing_region -v
```

Expected: Configuration errors properly detected.

## Performance Testing

### Token Generation Performance

```python
import time
from unittest.mock import patch, MagicMock
import base64

@patch('slurmweb.slurmrestd.pcs.boto3')
def test_performance(mock_boto3):
    from slurmweb.slurmrestd.pcs import PCSJwtProvider
    
    # Setup mock
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    test_key = b"test_key"
    mock_client.get_secret_value.return_value = {
        'SecretString': base64.b64encode(test_key).decode('utf-8'),
        'VersionId': 'v1'
    }
    
    provider = PCSJwtProvider(
        secret_id="arn:aws:secretsmanager:us-east-1:123:secret:test",
        region="us-east-1",
    )
    
    # Measure token generation time
    iterations = 1000
    start = time.time()
    for _ in range(iterations):
        token = provider.generate_token()
    end = time.time()
    
    avg_time = (end - start) / iterations * 1000  # ms
    print(f"Average token generation time: {avg_time:.3f}ms")
    
    # Should be < 10ms per token
    assert avg_time < 10.0
```

## Building the Project

### Build Python Package

```bash
# Build source distribution and wheel
python -m build

# Output will be in dist/
ls -l dist/
# Slurm-web-6.0.0.tar.gz
# Slurm_web-6.0.0-py3-none-any.whl
```

### Install Built Package

```bash
# Install from wheel
pip install dist/Slurm_web-6.0.0-py3-none-any.whl

# Install with PCS support
pip install "dist/Slurm_web-6.0.0-py3-none-any.whl[agent,pcs]"
```

### Build Documentation

```bash
# If documentation build tools are set up
cd docs
# Build with whatever doc system is used (Antora, Sphinx, etc.)
```

## Troubleshooting Tests

### Import Errors

If you see `ModuleNotFoundError: No module named 'slurmweb'`:

```bash
# Install in development mode
pip install -e .
```

### boto3 Not Found

```bash
pip install boto3
```

### Mock Issues

If mocks aren't working, ensure you're patching the correct location:

```python
# Patch where it's used, not where it's defined
@patch('slurmweb.slurmrestd.pcs.boto3')  # Correct
# not
@patch('boto3')  # Wrong
```

## Continuous Testing

Run tests automatically on file changes:

```bash
# Install pytest-watch
pip install pytest-watch

# Watch for changes
ptw slurmweb/tests/slurmrestd/test_pcs.py
```

## Test Checklist

Before committing changes:

- [ ] All PCS tests pass
- [ ] All authentication tests pass
- [ ] Code coverage > 80% for new code
- [ ] No regression in existing tests
- [ ] Documentation updated
- [ ] Example configuration tested

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
