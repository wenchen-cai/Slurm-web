# Copyright (c) 2025 Slurm-web contributors
#
# This file is part of Slurm-web.
#
# SPDX-License-Identifier: MIT

import unittest
from unittest.mock import Mock, patch, MagicMock
import time

from slurmweb.slurmrestd.pcs import PCSJwtProvider
from slurmweb.errors import SlurmwebConfigurationError


class TestPCSJwtProvider(unittest.TestCase):
    """Tests for AWS PCS JWT provider."""

    def setUp(self):
        """Set up test fixtures."""
        self.secret_id = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-key"
        self.region = "us-east-1"
        self.username = "test-user"

    @patch('slurmweb.slurmrestd.pcs.boto3')
    def test_init(self, mock_boto3):
        """Test PCS JWT provider initialization."""
        provider = PCSJwtProvider(
            secret_id=self.secret_id,
            region=self.region,
            username=self.username,
            uid=1000,
            gid=1000,
        )
        
        self.assertEqual(provider.secret_id, self.secret_id)
        self.assertEqual(provider.region, self.region)
        self.assertEqual(provider.username, self.username)
        self.assertEqual(provider.uid, 1000)
        self.assertEqual(provider.gid, 1000)

    @patch('slurmweb.slurmrestd.pcs.boto3')
    def test_fetch_signing_key(self, mock_boto3):
        """Test fetching signing key from Secrets Manager."""
        # Mock boto3 client
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # Mock secret response
        import base64
        test_key = b"test_secret_key"
        mock_client.get_secret_value.return_value = {
            'SecretString': base64.b64encode(test_key).decode('utf-8'),
            'VersionId': 'test-version-123'
        }
        
        provider = PCSJwtProvider(
            secret_id=self.secret_id,
            region=self.region,
        )
        
        # Trigger key fetch
        key = provider._fetch_signing_key()
        
        # Verify boto3 was called correctly
        mock_boto3.client.assert_called_with('secretsmanager', region_name=self.region)
        mock_client.get_secret_value.assert_called_with(SecretId=self.secret_id)
        
        # Verify key was decoded correctly
        self.assertEqual(key, test_key)
        self.assertEqual(provider._key_version, 'test-version-123')

    @patch('slurmweb.slurmrestd.pcs.boto3')
    def test_fetch_signing_key_access_denied(self, mock_boto3):
        """Test handling of AccessDenied error."""
        from botocore.exceptions import ClientError
        
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # Mock AccessDenied error
        mock_client.get_secret_value.side_effect = ClientError(
            {'Error': {'Code': 'AccessDeniedException'}},
            'GetSecretValue'
        )
        
        provider = PCSJwtProvider(
            secret_id=self.secret_id,
            region=self.region,
        )
        
        with self.assertRaises(ClientError):
            provider._fetch_signing_key()

    @patch('slurmweb.slurmrestd.pcs.boto3')
    @patch('slurmweb.slurmrestd.pcs.jwt')
    def test_generate_token(self, mock_jwt, mock_boto3):
        """Test JWT token generation."""
        import base64
        
        # Mock boto3 client
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        test_key = b"test_secret_key"
        mock_client.get_secret_value.return_value = {
            'SecretString': base64.b64encode(test_key).decode('utf-8'),
            'VersionId': 'test-version-123'
        }
        
        # Mock JWT encoding
        mock_jwt.encode.return_value = "test.jwt.token"
        
        provider = PCSJwtProvider(
            secret_id=self.secret_id,
            region=self.region,
            username=self.username,
            uid=1000,
            gid=1000,
            additional_gids=[1000, 100],
            token_lifetime=300,
        )
        
        # Generate token
        token = provider.generate_token()
        
        # Verify token was generated
        self.assertEqual(token, "test.jwt.token")
        
        # Verify JWT was encoded with correct parameters
        call_args = mock_jwt.encode.call_args
        payload = call_args[0][0]
        
        self.assertIn('exp', payload)
        self.assertIn('iat', payload)
        self.assertEqual(payload['sun'], self.username)
        self.assertEqual(payload['uid'], 1000)
        self.assertEqual(payload['gid'], 1000)
        self.assertIn('id', payload)
        self.assertEqual(payload['id']['gids'], [1000, 100])
        
        # Verify algorithm and key
        self.assertEqual(call_args[0][1], test_key)
        self.assertEqual(call_args[1]['algorithm'], 'HS256')

    @patch('slurmweb.slurmrestd.pcs.boto3')
    def test_generate_token_boto3_missing(self, mock_boto3):
        """Test error when boto3 is not installed."""
        mock_boto3.side_effect = ImportError("No module named 'boto3'")
        
        with self.assertRaises(ImportError) as cm:
            provider = PCSJwtProvider(
                secret_id=self.secret_id,
                region=self.region,
            )
            provider.generate_token()
        
        self.assertIn("boto3 is required", str(cm.exception))

    @patch('slurmweb.slurmrestd.pcs.boto3')
    @patch('slurmweb.slurmrestd.pcs.jwt')
    def test_token_expiration(self, mock_jwt, mock_boto3):
        """Test that tokens have correct expiration time."""
        import base64
        
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        test_key = b"test_secret_key"
        mock_client.get_secret_value.return_value = {
            'SecretString': base64.b64encode(test_key).decode('utf-8'),
            'VersionId': 'test-version-123'
        }
        
        mock_jwt.encode.return_value = "test.jwt.token"
        
        token_lifetime = 600  # 10 minutes
        provider = PCSJwtProvider(
            secret_id=self.secret_id,
            region=self.region,
            token_lifetime=token_lifetime,
        )
        
        before_time = int(time.time())
        provider.generate_token()
        after_time = int(time.time())
        
        # Get the payload that was passed to jwt.encode
        call_args = mock_jwt.encode.call_args
        payload = call_args[0][0]
        
        # Verify expiration is approximately correct
        expected_exp_min = before_time + token_lifetime
        expected_exp_max = after_time + token_lifetime
        
        self.assertGreaterEqual(payload['exp'], expected_exp_min)
        self.assertLessEqual(payload['exp'], expected_exp_max)

    @patch('slurmweb.slurmrestd.pcs.boto3')
    def test_refresh_key(self, mock_boto3):
        """Test forcing key refresh."""
        import base64
        
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # First key
        test_key_1 = b"test_key_1"
        # Second key (after rotation)
        test_key_2 = b"test_key_2"
        
        mock_client.get_secret_value.side_effect = [
            {
                'SecretString': base64.b64encode(test_key_1).decode('utf-8'),
                'VersionId': 'version-1'
            },
            {
                'SecretString': base64.b64encode(test_key_2).decode('utf-8'),
                'VersionId': 'version-2'
            }
        ]
        
        provider = PCSJwtProvider(
            secret_id=self.secret_id,
            region=self.region,
        )
        
        # Fetch first key
        key1 = provider._get_signing_key()
        self.assertEqual(key1, test_key_1)
        self.assertEqual(provider._key_version, 'version-1')
        
        # Refresh key
        provider.refresh_key()
        
        # Verify new key was fetched
        key2 = provider._get_signing_key()
        self.assertEqual(key2, test_key_2)
        self.assertEqual(provider._key_version, 'version-2')

    @patch('slurmweb.slurmrestd.pcs.boto3')
    def test_get_key_version(self, mock_boto3):
        """Test getting key version."""
        import base64
        
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        test_key = b"test_key"
        mock_client.get_secret_value.return_value = {
            'SecretString': base64.b64encode(test_key).decode('utf-8'),
            'VersionId': 'version-abc123'
        }
        
        provider = PCSJwtProvider(
            secret_id=self.secret_id,
            region=self.region,
        )
        
        # Initially no version
        self.assertIsNone(provider.get_key_version())
        
        # After fetching key
        provider._get_signing_key()
        self.assertEqual(provider.get_key_version(), 'version-abc123')


class TestPCSAuthentifierIntegration(unittest.TestCase):
    """Integration tests for PCS mode in SlurmrestdAuthentifier."""

    @patch('slurmweb.slurmrestd.auth.PCSJwtProvider')
    def test_pcs_mode_initialization(self, mock_pcs_provider_class):
        """Test that PCS mode initializes correctly."""
        from slurmweb.slurmrestd.auth import SlurmrestdAuthentifier
        from pathlib import Path
        
        mock_provider = MagicMock()
        mock_pcs_provider_class.return_value = mock_provider
        
        authentifier = SlurmrestdAuthentifier(
            method="jwt",
            jwt_mode="pcs",
            jwt_user="slurm-web",
            jwt_key=Path("/tmp/dummy.key"),
            jwt_lifespan=300,
            jwt_token=None,
            pcs_secret_id="arn:aws:secretsmanager:us-east-1:123:secret:key",
            pcs_region="us-east-1",
            pcs_uid=0,
            pcs_gid=0,
        )
        
        # Verify PCS provider was initialized
        mock_pcs_provider_class.assert_called_once()
        self.assertIsNotNone(authentifier.pcs_provider)

    @patch('slurmweb.slurmrestd.auth.PCSJwtProvider')
    def test_pcs_mode_missing_secret_id(self, mock_pcs_provider_class):
        """Test error when pcs_secret_id is missing."""
        from slurmweb.slurmrestd.auth import SlurmrestdAuthentifier
        from pathlib import Path
        
        with self.assertRaisesRegex(
            SlurmwebConfigurationError,
            "Missing pcs_secret_id in configuration"
        ):
            SlurmrestdAuthentifier(
                method="jwt",
                jwt_mode="pcs",
                jwt_user="slurm-web",
                jwt_key=Path("/tmp/dummy.key"),
                jwt_lifespan=300,
                jwt_token=None,
                pcs_secret_id=None,
                pcs_region="us-east-1",
            )

    @patch('slurmweb.slurmrestd.auth.PCSJwtProvider')
    def test_pcs_mode_missing_region(self, mock_pcs_provider_class):
        """Test error when pcs_region is missing."""
        from slurmweb.slurmrestd.auth import SlurmrestdAuthentifier
        from pathlib import Path
        
        with self.assertRaisesRegex(
            SlurmwebConfigurationError,
            "Missing pcs_region in configuration"
        ):
            SlurmrestdAuthentifier(
                method="jwt",
                jwt_mode="pcs",
                jwt_user="slurm-web",
                jwt_key=Path("/tmp/dummy.key"),
                jwt_lifespan=300,
                jwt_token=None,
                pcs_secret_id="arn:aws:secretsmanager:us-east-1:123:secret:key",
                pcs_region=None,
            )

    @patch('slurmweb.slurmrestd.auth.PCSJwtProvider')
    def test_pcs_mode_headers(self, mock_pcs_provider_class):
        """Test that PCS mode generates fresh headers."""
        from slurmweb.slurmrestd.auth import SlurmrestdAuthentifier
        from pathlib import Path
        
        mock_provider = MagicMock()
        mock_provider.generate_token.return_value = "fresh.pcs.token"
        mock_pcs_provider_class.return_value = mock_provider
        
        authentifier = SlurmrestdAuthentifier(
            method="jwt",
            jwt_mode="pcs",
            jwt_user="slurm-web",
            jwt_key=Path("/tmp/dummy.key"),
            jwt_lifespan=300,
            jwt_token=None,
            pcs_secret_id="arn:aws:secretsmanager:us-east-1:123:secret:key",
            pcs_region="us-east-1",
        )
        
        # Get headers
        headers = authentifier.headers()
        
        # Verify fresh token was generated
        mock_provider.generate_token.assert_called_once()
        
        # Verify headers are correct
        self.assertEqual(headers["X-SLURM-USER-NAME"], "slurm-web")
        self.assertEqual(headers["X-SLURM-USER-TOKEN"], "fresh.pcs.token")
