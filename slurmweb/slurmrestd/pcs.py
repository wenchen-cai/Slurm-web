#!/usr/bin/env python3
# Copyright (c) 2025 Slurm-web contributors
#
# This file is part of Slurm-web.
#
# SPDX-License-Identifier: MIT

"""AWS PCS JWT authentication provider for Slurm REST API."""

import base64
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PCSJwtProvider:
    """Provider for AWS PCS JWT tokens.
    
    This provider generates JWT tokens for authenticating with slurmrestd
    in AWS Parallel Computing Service (PCS) environments. The signing key
    is retrieved from AWS Secrets Manager and tokens are generated with
    POSIX user identity claims required by PCS.
    """

    def __init__(
        self,
        secret_id: str,
        region: str,
        username: str = "slurm-web",
        uid: int = 0,
        gid: int = 0,
        additional_gids: Optional[list] = None,
        gecos: str = "Slurm Web Agent",
        home_dir: str = "/",
        shell: str = "/sbin/nologin",
        token_lifetime: int = 300,
    ):
        """Initialize PCS JWT provider.
        
        Args:
            secret_id: AWS Secrets Manager secret ARN or name
            region: AWS region where the secret is stored
            username: Username for JWT sun claim (default: slurm-web)
            uid: POSIX user ID (default: 0)
            gid: POSIX group ID (default: 0)
            additional_gids: Additional group IDs (default: [0])
            gecos: User GECOS field (default: Slurm Web Agent)
            home_dir: User home directory (default: /)
            shell: User shell (default: /sbin/nologin)
            token_lifetime: Token lifetime in seconds (default: 300)
        """
        self.secret_id = secret_id
        self.region = region
        self.username = username
        self.uid = uid
        self.gid = gid
        self.additional_gids = additional_gids or [0]
        self.gecos = gecos
        self.home_dir = home_dir
        self.shell = shell
        self.token_lifetime = token_lifetime
        
        self._signing_key: Optional[bytes] = None
        self._key_version: Optional[str] = None
        
        logger.info(
            f"PCS JWT provider initialized for secret {secret_id} in region {region}"
        )

    def _fetch_signing_key(self) -> bytes:
        """Fetch the JWT signing key from AWS Secrets Manager.
        
        Returns:
            The decoded signing key as bytes
            
        Raises:
            ImportError: If boto3 is not installed
            Exception: If key retrieval fails
        """
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            raise ImportError(
                "boto3 is required for PCS JWT authentication. "
                "Install it with: pip install boto3"
            )
        
        try:
            client = boto3.client("secretsmanager", region_name=self.region)
            
            response = client.get_secret_value(SecretId=self.secret_id)
            
            self._key_version = response.get("VersionId")
            
            # The secret value is base64 encoded
            secret_string = response["SecretString"]
            signing_key = base64.b64decode(secret_string)
            
            logger.info(
                f"Successfully retrieved signing key from Secrets Manager "
                f"(version: {self._key_version})"
            )
            
            return signing_key
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error(
                f"Failed to retrieve signing key from Secrets Manager: "
                f"{error_code} - {str(e)}"
            )
            raise
        except Exception as e:
            logger.error(f"Unexpected error retrieving signing key: {str(e)}")
            raise

    def _get_signing_key(self) -> bytes:
        """Get the signing key, fetching if necessary.
        
        Returns:
            The signing key as bytes
        """
        if self._signing_key is None:
            self._signing_key = self._fetch_signing_key()
        return self._signing_key

    def generate_token(self) -> str:
        """Generate a new PCS JWT token.
        
        The token includes all required claims for AWS PCS authentication:
        - exp: Expiration time
        - iat: Issued at time
        - sun: Username
        - uid: POSIX user ID
        - gid: POSIX group ID
        - id: Additional POSIX identity properties
        
        Returns:
            Encoded JWT token as a string
            
        Raises:
            Exception: If token generation fails
        """
        try:
            import jwt
        except ImportError:
            raise ImportError(
                "PyJWT is required for PCS JWT authentication. "
                "Install it with: pip install PyJWT"
            )
        
        now = int(time.time())
        
        payload = {
            "exp": now + self.token_lifetime,
            "iat": now,
            "sun": self.username,
            "uid": self.uid,
            "gid": self.gid,
            "id": {
                "gecos": self.gecos,
                "dir": self.home_dir,
                "shell": self.shell,
                "gids": self.additional_gids,
            },
        }
        
        try:
            signing_key = self._get_signing_key()
            token = jwt.encode(payload, signing_key, algorithm="HS256")
            
            logger.debug(
                f"Generated PCS JWT token for user {self.username} "
                f"(uid={self.uid}, gid={self.gid}, expires in {self.token_lifetime}s)"
            )
            
            return token
            
        except Exception as e:
            logger.error(f"Failed to generate PCS JWT token: {str(e)}")
            raise

    def refresh_key(self) -> None:
        """Force refresh of the signing key from Secrets Manager.
        
        This is useful when the key has been rotated in AWS Secrets Manager.
        """
        logger.info("Refreshing signing key from Secrets Manager")
        self._signing_key = None
        self._fetch_signing_key()

    def get_key_version(self) -> Optional[str]:
        """Get the current version ID of the signing key.
        
        Returns:
            The version ID of the current signing key, or None if not yet fetched
        """
        return self._key_version
