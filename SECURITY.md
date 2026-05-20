# Security

garmin-sync stores personal health data and API credentials locally. This document describes the security controls in place.

## Data Privacy

- **All data stays on your machine.** The SQLite database, FIT files, reports, and configuration are stored in platform-specific local directories (see [README.md](README.md#data-storage) for paths).
- **No telemetry or analytics.** garmin-sync does not phone home.
- **Third-party API calls are opt-in:**
  - Garmin Connect and HEVY APIs are contacted only when you run `sync` commands.
  - OpenAI is contacted only when you use `analyze` or `chat` commands with AI features configured.

## File Permissions

On macOS and Linux, sensitive files are restricted to owner-only access:

| Target | Permission | Notes |
|--------|-----------|-------|
| `config.toml` (API keys) | `0o600` | Set on every write by `ai/config.py` |
| OAuth tokens (`~/.garminconnect/`) | `0o600` / `0o700` | Set by `auth/garmin_auth.py` |
| SQLite database | `0o600` | Set on connection open by `db/database.py` |
| Analysis reports | `0o600` | Set by `reports/report_generator.py` |
| Data directories | `0o700` | Set by `config/settings.py` via `ensure_directories()` |

All `chmod` calls are wrapped in `try/except OSError` so they silently no-op on **Windows**, where NTFS default permissions (user-owned files) provide equivalent protection.

## Credential Storage

| Credential | Storage Location | Protection |
|------------|-----------------|------------|
| Garmin OAuth tokens | `~/.garminconnect/` | File permissions `0o600`; managed by the `garth` library |
| HEVY API key | `config.toml` | File permissions `0o600` |
| OpenAI API key | `config.toml` | File permissions `0o600` |

Credentials can alternatively be set via environment variables (prefix `GARMIN_SYNC_`) but config file storage is the default and recommended method.

## .gitignore Defense-in-Depth

The repository `.gitignore` blocks accidental commits of sensitive or personal data:

- `config.toml` - Contains API keys
- `.garminconnect/` - OAuth tokens
- `*.db` - SQLite databases with personal health data
- `*.fit` - FIT files (personal activity data)
- `reports/` - AI analysis reports (personal health data)
- `data/` - Local data storage
- `.env` / `.env.local` - Environment files

## Input Validation

### LLM Prompt Injection Defense

HEVY workout data (titles, exercise names) comes from user-controlled or shared content that could contain prompt injection attempts:

1. **`safe_user_string()`** (in `ai/prompt_builder.py`): Strips control characters and `<>` from all HEVY-derived strings before they reach the LLM.
2. **XML tag wrapping**: Sanitized data is wrapped in `<hevy_title>` / `<hevy_exercise>` tags, and the system prompt explicitly instructs the model to treat tagged content as inert data.
3. **Tool error sanitization**: Tool exceptions surface a generic `{"error": "Tool execution failed"}` to the model; full traces go to stderr only (prevents data exfiltration via error messages).

### SQL Injection Defense

- **`_ALLOWED_DAILY_TABLES` frozenset** (in `db/repository.py`): The `has_daily_record()` method validates dynamic table names against a hardcoded allowlist before interpolation. Invalid names raise `ValueError`.
- **Parameterized queries**: All other database operations use `?` parameter binding, never string interpolation of user input.

### CLI Input Validation

- **Date inputs**: The `analyze view --date` command validates date strings against `^\d{4}-\d{2}-\d{2}$` regex before use.
- **Numeric ranges**: Pydantic `Field` constraints enforce valid ranges on all settings (`ge=`, `le=`).

### Shell Command Safety

- **macOS launchd**: `shlex.quote()` is applied to all paths embedded in the shell command within the generated plist file (`scheduler/launchd.py`).
- **Windows Task Scheduler**: `_validate_batch_path()` rejects paths containing any of `"&|<>^%!` before writing the batch wrapper script (`scheduler/windows_task.py`).

## API Security

### Rate Limiting

- **Garmin Connect**: Token bucket algorithm (`api/rate_limiter.py`) enforces a configurable rate limit (default: 15 calls/min). Prevents account throttling or temporary bans.
- **HEVY API**: 0.5-second minimum request interval plus exponential backoff on failures. 429 responses are handled with `Retry-After` header.

### Error Handling

- **Sanitized error messages**: API error responses may contain tokens or sensitive data. Full responses are logged to stderr only; raised exceptions contain generic messages like `"API error: HTTP {status_code}"`.
- **No retry on auth failures**: 401 and 403 responses raise immediately without retrying, preventing credential brute-force loops.
- **Exponential backoff**: Transient failures use `2^attempt` second delays, capped at `max_retries` (default: 3).

## Reporting Vulnerabilities

If you discover a security vulnerability, please email **https://github.com/jdellag/garmin-sync/issues** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact

Please allow reasonable time for a fix before public disclosure.
