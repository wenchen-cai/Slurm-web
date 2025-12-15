# Copyright (c) 2025 Rackslab
#
# This file is part of Slurm-web.
#
# SPDX-License-Identifier: MIT

import typing as t
import time
from pathlib import Path
import logging

from rfl.authentication.jwt import (
    jwt_validate_expiration,
    JWTBaseManager,
    JWTPrivateKeyFileLoader,
)
from rfl.authentication.errors import JWTDecodeError, JWTPrivateKeyLoaderError

from ..errors import SlurmwebConfigurationError
from .pcs import PCSJwtProvider


logger = logging.getLogger(__name__)


class SlurmrestdAuthentifier:
    def __init__(
        self,
        method: str,
        jwt_mode: str,
        jwt_user: str,
        jwt_key: Path,
        jwt_lifespan: int,
        jwt_token: t.Optional[str],
        pcs_secret_id: t.Optional[str] = None,
        pcs_region: t.Optional[str] = None,
        pcs_uid: int = 0,
        pcs_gid: int = 0,
        pcs_gids: t.Optional[t.List[int]] = None,
        pcs_gecos: str = "Slurm Web Agent",
        pcs_home_dir: str = "/",
        pcs_shell: str = "/sbin/nologin",
    ):
        self.method = method
        self.jwt_mode = jwt_mode
        self.jwt_user = jwt_user
        self.jwt_key = jwt_key
        self.jwt_lifespan = jwt_lifespan
        self.jwt_token = None
        self.jwt_manager = None
        self.pcs_provider = None

        # With local authentication, nothing more is needed.
        if self.method == "local":
            return

        # In static mode, check token is defined in configuration and check its validity
        # (format and expiration).
        if self.jwt_mode == "static":
            if not jwt_token:
                raise SlurmwebConfigurationError(
                    "Missing token in configuration for slurmrestd jwt authentication "
                    "in static mode"
                )
            self.jwt_token = jwt_token
            try:
                payload = jwt_validate_expiration(self.jwt_token)
            except JWTDecodeError as err:
                raise SlurmwebConfigurationError(
                    f"Invalid slurmrestd JWT: {err}"
                ) from err
            self.expiration = payload["exp"]
            return

        # In pcs mode, initialize AWS PCS JWT provider to generate tokens with
        # Secrets Manager signing key.
        if self.jwt_mode == "pcs":
            if not pcs_secret_id:
                raise SlurmwebConfigurationError(
                    "Missing pcs_secret_id in configuration for slurmrestd jwt "
                    "authentication in PCS mode"
                )
            if not pcs_region:
                raise SlurmwebConfigurationError(
                    "Missing pcs_region in configuration for slurmrestd jwt "
                    "authentication in PCS mode"
                )
            try:
                self.pcs_provider = PCSJwtProvider(
                    secret_id=pcs_secret_id,
                    region=pcs_region,
                    username=jwt_user,
                    uid=pcs_uid,
                    gid=pcs_gid,
                    additional_gids=pcs_gids or [pcs_gid],
                    gecos=pcs_gecos,
                    home_dir=pcs_home_dir,
                    shell=pcs_shell,
                    token_lifetime=jwt_lifespan,
                )
                logger.info("AWS PCS JWT authentication mode initialized")
            except ImportError as err:
                raise SlurmwebConfigurationError(
                    f"Unable to initialize PCS JWT provider: {err}"
                ) from err
            except Exception as err:
                raise SlurmwebConfigurationError(
                    f"Failed to initialize PCS JWT provider: {err}"
                ) from err
            return

        # In auto mode, initialize JWT manager to generate tokens dynamically.
        try:
            self.jwt_manager = JWTBaseManager(
                "HS256", JWTPrivateKeyFileLoader(path=self.jwt_key)
            )
        except JWTPrivateKeyLoaderError as err:
            raise SlurmwebConfigurationError(
                f"Unable to load JWT key for slurmrestd authentication: {err}"
            ) from err

    def _generate_token(self) -> str:
        """Generate and return token with Slurm shared JWT signature key in auto
        mode."""
        self.expiration = int(time.time()) + self.jwt_lifespan
        return self.jwt_manager.generate(
            duration=self.jwt_lifespan / 86400, claimset={"sun": self.jwt_user}
        )

    def _generate_pcs_token(self) -> str:
        """Generate and return token with AWS PCS signing key in PCS mode."""
        try:
            return self.pcs_provider.generate_token()
        except Exception as err:
            raise SlurmwebConfigurationError(
                f"Failed to generate PCS JWT token: {err}"
            ) from err

    def headers(self) -> t.Dict[str, str]:
        """Return dictionary of HTTP headers for authentication to slurmrestd"""
        if self.method == "local":
            return {}

        if self.jwt_mode == "static":
            gap = self.expiration - int(time.time())
            if gap < 0:
                logger.error("Static JWT for slurmrestd authentication is expired")
            elif gap < 3600:
                logger.warning(
                    "Static JWT for slurmrestd authentication will expire soon"
                )
        elif self.jwt_mode == "pcs":
            # In PCS mode, always generate a fresh token for each request
            # as tokens are short-lived (typically 5 minutes)
            logger.debug("Generating fresh PCS JWT for authentication to slurmrestd")
            self.jwt_token = self._generate_pcs_token()
        else:
            if not self.jwt_token:
                logger.info("Generating new JWT for authentication to slurmrestd")
                self.jwt_token = self._generate_token()
            gap = self.expiration - int(time.time())
            if gap < 60:
                logger.info("Renewing JWT for authentication to slurmrestd")
                self.jwt_token = self._generate_token()

        return {
            "X-SLURM-USER-NAME": self.jwt_user,
            "X-SLURM-USER-TOKEN": self.jwt_token,
        }
