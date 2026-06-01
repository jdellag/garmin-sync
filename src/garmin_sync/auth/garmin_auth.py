"""Garmin Connect authentication management."""

import logging
import sys
from pathlib import Path
from typing import Callable, Optional

from garminconnect import Garmin

from garmin_sync.config.paths import default_garth_token_dir

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Authentication with Garmin Connect failed."""
    pass


class TokenExpiredError(AuthenticationError):
    """OAuth tokens have expired and need refresh."""
    pass


class GarminAuthManager:
    """Manages Garmin Connect authentication via Garth OAuth."""

    def __init__(self, token_dir: Optional[Path] = None):
        """Initialize auth manager.

        Args:
            token_dir: Directory for storing OAuth tokens.
                      Defaults to ~/.garminconnect
        """
        self.token_dir = token_dir or default_garth_token_dir()
        self._client: Optional[Garmin] = None

    @property
    def client(self) -> Garmin:
        """Get authenticated Garmin client.

        Raises:
            AuthenticationError: If not authenticated.
        """
        if self._client is None:
            raise AuthenticationError(
                "Not authenticated. Please run 'garmin-sync auth login' first."
            )
        return self._client

    def login(
        self,
        email: str,
        password: str,
        prompt_mfa: Optional[Callable[[], str]] = None,
    ) -> bool:
        """Login to Garmin Connect with email and password.

        Args:
            email: Garmin account email
            password: Garmin account password
            prompt_mfa: Optional callable returning a 2FA/MFA code. Defaults to
                a stdin prompt so accounts with two-factor auth enabled can
                complete login instead of failing with an opaque error.

        Returns:
            True if login successful

        Raises:
            AuthenticationError: If login fails
        """
        if prompt_mfa is None:
            def prompt_mfa() -> str:
                return input("Garmin MFA/2FA code: ")

        try:
            # Garmin handles garth internally; pass an MFA prompt so a 2FA
            # account gets a code prompt rather than an opaque profile error.
            self._client = Garmin(email, password, prompt_mfa=prompt_mfa)
            self._client.login()

            # Save tokens using Garmin's garth client
            self._ensure_token_dir()
            self._client.garth.dump(str(self.token_dir))

            # Tighten permissions on the token files themselves; garth writes
            # them with the process umask (typically 0o644).
            for token_file in self.token_dir.glob("*.json"):
                try:
                    token_file.chmod(0o600)
                except OSError as e:
                    print(
                        f"Warning: could not chmod {token_file}: {e}",
                        file=sys.stderr,
                    )

            # The password is only needed for the SSO exchange; drop it now so
            # it doesn't linger in the long-lived client object.
            try:
                self._client.password = None
            except Exception:
                pass

            return True

        except Exception as e:
            raise AuthenticationError(f"Login failed: {e}") from e

    def resume_session(self) -> bool:
        """Resume session from saved tokens.

        Returns:
            True if session resumed successfully, False if re-login needed.
        """
        if not self.has_tokens():
            return False

        try:
            # Create Garmin client and load tokens from tokenstore
            self._client = Garmin()
            self._client.login(tokenstore=str(self.token_dir))
            return True

        except Exception:
            # Could be expired/corrupt tokens or a transient network error.
            # Don't swallow silently — log so failures are diagnosable.
            logger.debug("Could not resume session from saved tokens", exc_info=True)
            return False

    def logout(self) -> None:
        """Clear saved authentication tokens."""
        import shutil

        if self.token_dir.exists():
            shutil.rmtree(self.token_dir)

        self._client = None

    def has_tokens(self) -> bool:
        """Check whether usable OAuth tokens exist.

        garth always creates both token files but writes content only when a
        token is actually present, so a partial/interrupted login can leave
        0-byte files. Require a non-empty file rather than mere existence,
        otherwise the auth gate passes and the real failure surfaces later.
        """
        def _nonempty(name: str) -> bool:
            p = self.token_dir / name
            try:
                return p.exists() and p.stat().st_size > 0
            except OSError:
                return False

        return _nonempty("oauth1_token.json") or _nonempty("oauth2_token.json")

    def get_status(self) -> dict:
        """Get current authentication status.

        Returns:
            Dict with authentication status information.
        """
        has_tokens = self.has_tokens()
        is_valid = False

        if has_tokens:
            is_valid = self.resume_session()

        return {
            "authenticated": is_valid,
            "has_tokens": has_tokens,
            "token_dir": str(self.token_dir),
        }

    def ensure_authenticated(self) -> Garmin:
        """Ensure we have a valid authenticated client.

        Returns:
            Authenticated Garmin client.

        Raises:
            AuthenticationError: If not authenticated and can't resume.
        """
        if self._client is not None:
            return self._client

        if not self.resume_session():
            raise AuthenticationError(
                "Not authenticated. Please run 'garmin-sync auth login' first."
            )

        return self._client

    def _ensure_token_dir(self) -> None:
        """Create token directory with secure permissions."""
        self.token_dir.mkdir(parents=True, exist_ok=True)

        # Set restrictive permissions (owner only)
        try:
            self.token_dir.chmod(0o700)
        except OSError as e:
            print(
                f"Warning: could not chmod token dir {self.token_dir}: {e}",
                file=sys.stderr,
            )


# Global auth manager instance
_auth_manager: Optional[GarminAuthManager] = None


def get_auth_manager(token_dir: Optional[Path] = None) -> GarminAuthManager:
    """Get or create the global auth manager instance."""
    global _auth_manager

    if _auth_manager is None or (token_dir and _auth_manager.token_dir != token_dir):
        _auth_manager = GarminAuthManager(token_dir)

    return _auth_manager
