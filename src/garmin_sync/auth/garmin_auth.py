"""Garmin Connect authentication management."""

import sys
from pathlib import Path
from typing import Optional

from garminconnect import Garmin

from garmin_sync.config.paths import default_garth_token_dir


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

    def login(self, email: str, password: str) -> bool:
        """Login to Garmin Connect with email and password.

        Args:
            email: Garmin account email
            password: Garmin account password

        Returns:
            True if login successful

        Raises:
            AuthenticationError: If login fails
        """
        try:
            # Use Garmin class directly - it handles garth internally
            self._client = Garmin(email, password)
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
            return False

    def logout(self) -> None:
        """Clear saved authentication tokens."""
        import shutil

        if self.token_dir.exists():
            shutil.rmtree(self.token_dir)

        self._client = None

    def has_tokens(self) -> bool:
        """Check if OAuth tokens exist."""
        oauth1_token = self.token_dir / "oauth1_token.json"
        oauth2_token = self.token_dir / "oauth2_token.json"
        return oauth1_token.exists() or oauth2_token.exists()

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
