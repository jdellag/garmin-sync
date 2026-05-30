# Getting Started

## Requirements

- **Python 3.10+**
- **Garmin Connect account** with a compatible Garmin device
- **Platform:** macOS (primary), Windows 11 (fully supported). Linux works for all features except automatic scheduling (use crontab manually).

## Installation

```bash
git clone https://github.com/jdellag/garmin-sync.git
cd garmin-sync
pip install -e .

# Verify
garmin-sync --version
```

## Setup

### Interactive wizard (recommended)

```bash
garmin-sync setup
```

The wizard walks you through:

1. **Garmin Connect login** -- OAuth authentication (same method as the official app)
2. **OpenAI API key** -- for AI-powered analysis and chat
3. **Training profile** -- your schedule, goals, and timezone
4. **HEVY integration** -- optional strength training data from the HEVY app

### Manual setup

```bash
# 1. Login to Garmin Connect
garmin-sync auth login

# 2. Configure AI and training profile
garmin-sync analyze configure

# 3. (Optional) Configure HEVY strength tracking
garmin-sync hevy login
```

After setup, your configuration lives in two files:

| File | Contents | Permissions |
|------|----------|-------------|
| `config.toml` | API keys, model settings | `0o600` (owner-only) |
| `profile.toml` | Training schedule, goals, timezone | `0o644` (readable) |

See [Configuration](configuration.md) for full details and file locations.

## First sync

```bash
# Sync the last 30 days of data
garmin-sync sync all

# Preview what would be synced without making API calls
garmin-sync sync all --dry-run
```

This fetches activities, sleep, heart rate, stress, HRV, body battery, training readiness, and (if configured) HEVY workouts. Data is stored in a local SQLite database.

## First chat

```bash
garmin-sync analyze chat
```

The AI coach loads your recent data automatically. Ask questions like:

- "How has my bench press progressed over the last 3 months?"
- "What's my recovery status today?"
- "Am I ready for a hard workout?"

Type `/quit` to exit. See [AI Chat & Analysis](ai-chat.md) for all commands.

## Quick daily workflow

```bash
garmin-sync sync all           # Sync latest data
garmin-sync analyze chat       # Talk to your AI coach
garmin-sync stats today        # Quick summary
```

Or set up [automatic scheduling](scheduling.md) to sync daily without manual commands.

## Next steps

- [CLI Reference](cli-reference.md) -- all commands and flags
- [AI Chat & Analysis](ai-chat.md) -- interactive coaching, analysis reports
- [MCP Integration](mcp-integration.md) -- use your data in Claude Desktop
- [HEVY Integration](hevy-integration.md) -- strength training tracking
- [Configuration](configuration.md) -- TOML files, environment variables, data paths
- [Scheduling](scheduling.md) -- automatic daily sync
