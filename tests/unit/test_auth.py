"""Tests for authentication module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from garmin_sync.auth.garmin_auth import (
    AuthenticationError,
    GarminAuthManager,
    get_auth_manager,
)


class TestGarminAuthManager:
    """Test GarminAuthManager class."""

    def test_default_token_dir(self):
        """Test default token directory."""
        manager = GarminAuthManager()
        assert manager.token_dir == Path.home() / ".garminconnect"

    def test_custom_token_dir(self, temp_dir):
        """Test custom token directory."""
        manager = GarminAuthManager(token_dir=temp_dir / "tokens")
        assert manager.token_dir == temp_dir / "tokens"

    def test_client_not_authenticated(self, temp_dir):
        """Test accessing client when not authenticated."""
        manager = GarminAuthManager(token_dir=temp_dir)

        with pytest.raises(AuthenticationError) as exc_info:
            _ = manager.client

        assert "Not authenticated" in str(exc_info.value)

    def test_has_tokens_no_tokens(self, temp_dir):
        """Test has_tokens when no tokens exist."""
        manager = GarminAuthManager(token_dir=temp_dir / "tokens")
        assert manager.has_tokens() is False

    def test_has_tokens_with_oauth1(self, temp_dir):
        """Test has_tokens with OAuth1 token."""
        token_dir = temp_dir / "tokens"
        token_dir.mkdir(parents=True)
        (token_dir / "oauth1_token.json").write_text("{}")

        manager = GarminAuthManager(token_dir=token_dir)
        assert manager.has_tokens() is True

    def test_has_tokens_with_oauth2(self, temp_dir):
        """Test has_tokens with OAuth2 token."""
        token_dir = temp_dir / "tokens"
        token_dir.mkdir(parents=True)
        (token_dir / "oauth2_token.json").write_text("{}")

        manager = GarminAuthManager(token_dir=token_dir)
        assert manager.has_tokens() is True

    @patch("garmin_sync.auth.garmin_auth.Garmin")
    def test_login_success(self, mock_garmin_class, temp_dir):
        """Test successful login."""
        mock_client = MagicMock()
        mock_client.garth = MagicMock()
        mock_garmin_class.return_value = mock_client

        manager = GarminAuthManager(token_dir=temp_dir / "tokens")
        result = manager.login("test@example.com", "password123")

        assert result is True
        # Garmin client is created with credentials (+ an MFA prompt callback).
        assert mock_garmin_class.call_count == 1
        call = mock_garmin_class.call_args
        assert call.args == ("test@example.com", "password123")
        assert callable(call.kwargs.get("prompt_mfa"))
        mock_client.login.assert_called_once()
        # Tokens are saved using client's garth instance
        mock_client.garth.dump.assert_called_once()
        # Password is dropped from the client after the token dump.
        assert mock_client.password is None

    @patch("garmin_sync.auth.garmin_auth.Garmin")
    def test_login_uses_provided_mfa_prompt(self, mock_garmin_class, temp_dir):
        """A caller-supplied MFA prompt is forwarded to Garmin so 2FA accounts
        can authenticate instead of failing opaquely."""
        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client

        def my_prompt():
            return "123456"

        manager = GarminAuthManager(token_dir=temp_dir / "tokens")
        manager.login("e@x.com", "pw", prompt_mfa=my_prompt)

        assert mock_garmin_class.call_args.kwargs["prompt_mfa"] is my_prompt

    def test_has_tokens_false_for_empty_files(self, temp_dir):
        """0-byte token files (from an interrupted login) are not 'usable'."""
        token_dir = temp_dir / "tokens"
        token_dir.mkdir(parents=True)
        (token_dir / "oauth1_token.json").write_text("")
        (token_dir / "oauth2_token.json").write_text("")

        manager = GarminAuthManager(token_dir=token_dir)
        assert manager.has_tokens() is False

    @patch("garmin_sync.auth.garmin_auth.Garmin")
    def test_login_failure(self, mock_garmin_class, temp_dir):
        """Test failed login."""
        mock_client = MagicMock()
        mock_client.login.side_effect = Exception("Invalid credentials")
        mock_garmin_class.return_value = mock_client

        manager = GarminAuthManager(token_dir=temp_dir / "tokens")

        with pytest.raises(AuthenticationError) as exc_info:
            manager.login("test@example.com", "wrongpassword")

        assert "Login failed" in str(exc_info.value)

    def test_resume_session_no_tokens(self, temp_dir):
        """Test resume_session when no tokens exist."""
        manager = GarminAuthManager(token_dir=temp_dir / "tokens")
        result = manager.resume_session()
        assert result is False

    @patch("garmin_sync.auth.garmin_auth.Garmin")
    def test_resume_session_success(self, mock_garmin_class, temp_dir):
        """Test successful session resume."""
        # Create token files
        token_dir = temp_dir / "tokens"
        token_dir.mkdir(parents=True)
        (token_dir / "oauth1_token.json").write_text("{}")

        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client

        manager = GarminAuthManager(token_dir=token_dir)
        result = manager.resume_session()

        assert result is True
        mock_garmin_class.assert_called_once_with()
        mock_client.login.assert_called_once_with(tokenstore=str(token_dir))

    @patch("garmin_sync.auth.garmin_auth.Garmin")
    def test_resume_session_failure(self, mock_garmin_class, temp_dir):
        """Test failed session resume."""
        # Create token files
        token_dir = temp_dir / "tokens"
        token_dir.mkdir(parents=True)
        (token_dir / "oauth1_token.json").write_text("{}")

        mock_client = MagicMock()
        mock_client.login.side_effect = Exception("Token expired")
        mock_garmin_class.return_value = mock_client

        manager = GarminAuthManager(token_dir=token_dir)
        result = manager.resume_session()

        assert result is False

    def test_logout(self, temp_dir):
        """Test logout clears tokens."""
        token_dir = temp_dir / "tokens"
        token_dir.mkdir(parents=True)
        (token_dir / "oauth1_token.json").write_text("{}")

        manager = GarminAuthManager(token_dir=token_dir)

        # Verify tokens exist
        assert manager.has_tokens() is True

        # Logout
        manager.logout()

        # Verify tokens are removed
        assert token_dir.exists() is False
        assert manager._client is None

    def test_get_status_not_authenticated(self, temp_dir):
        """Test get_status when not authenticated."""
        manager = GarminAuthManager(token_dir=temp_dir / "tokens")
        status = manager.get_status()

        assert status["authenticated"] is False
        assert status["has_tokens"] is False
        assert "tokens" in status["token_dir"]

    @patch("garmin_sync.auth.garmin_auth.Garmin")
    def test_get_status_authenticated(self, mock_garmin_class, temp_dir):
        """Test get_status when authenticated."""
        # Create token files
        token_dir = temp_dir / "tokens"
        token_dir.mkdir(parents=True)
        (token_dir / "oauth1_token.json").write_text("{}")

        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client

        manager = GarminAuthManager(token_dir=token_dir)
        status = manager.get_status()

        assert status["authenticated"] is True
        assert status["has_tokens"] is True

    def test_ensure_authenticated_not_authenticated(self, temp_dir):
        """Test ensure_authenticated when not authenticated."""
        manager = GarminAuthManager(token_dir=temp_dir / "tokens")

        with pytest.raises(AuthenticationError):
            manager.ensure_authenticated()

    @patch("garmin_sync.auth.garmin_auth.Garmin")
    def test_ensure_authenticated_with_resume(self, mock_garmin_class, temp_dir):
        """Test ensure_authenticated resumes session."""
        # Create token files
        token_dir = temp_dir / "tokens"
        token_dir.mkdir(parents=True)
        (token_dir / "oauth1_token.json").write_text("{}")

        mock_client = MagicMock()
        mock_garmin_class.return_value = mock_client

        manager = GarminAuthManager(token_dir=token_dir)
        client = manager.ensure_authenticated()

        assert client is not None
        # Verify resume_session was called with tokenstore
        mock_garmin_class.assert_called_once_with()
        mock_client.login.assert_called_once_with(tokenstore=str(token_dir))

    def test_token_dir_created_with_permissions(self, temp_dir):
        """Test token directory is created with secure permissions."""
        manager = GarminAuthManager(token_dir=temp_dir / "secure_tokens")
        manager._ensure_token_dir()

        assert manager.token_dir.exists()
        # Check permissions (700 = owner read/write/execute only)
        mode = manager.token_dir.stat().st_mode & 0o777
        assert mode == 0o700


class TestGetAuthManager:
    """Test get_auth_manager function."""

    def test_get_auth_manager_singleton(self):
        """Test that get_auth_manager returns same instance."""
        import garmin_sync.auth.garmin_auth as auth_module

        # Reset global state
        auth_module._auth_manager = None

        manager1 = get_auth_manager()
        manager2 = get_auth_manager()

        assert manager1 is manager2

    def test_get_auth_manager_with_custom_dir(self, temp_dir):
        """Test get_auth_manager with custom directory."""
        import garmin_sync.auth.garmin_auth as auth_module

        # Reset global state
        auth_module._auth_manager = None

        manager = get_auth_manager(token_dir=temp_dir / "custom")

        assert manager.token_dir == temp_dir / "custom"
