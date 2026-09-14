# garmin-sync

A command-line tool that syncs your Garmin Connect and HEVY fitness data locally, with AI-powered analysis via OpenAI and MCP (Model Context Protocol) integration for Claude Desktop. Works on **macOS** and **Windows 11**.

## Features

- **Comprehensive Data Sync** -- Activities, sleep, heart rate, stress, HRV, body battery, training readiness from Garmin Connect
- **HEVY Integration** -- Strength training data with volume tracking, muscle group set targets, and exercise progression
- **AI Fitness Coach** -- Interactive chat with tool calling for on-demand data queries
- **MCP Server** -- Use your fitness data directly in Claude Desktop
- **Computed Analytics** -- Training load, HR drift, A:C load-ramp ratio, pacing analysis, anomaly detection, personal records
- **Longitudinal Review** -- Multi-year trend analysis surfacing plateaus and regime shifts
- **Cross-Platform Scheduling** -- Automatic daily sync via launchd (macOS) or Task Scheduler (Windows)
- **Smart Sync** -- Skips unchanged daily metrics to save API calls (`--dry-run` to preview, `--force` to override)
- **Local Storage** -- All data in a SQLite database you control (see [SECURITY.md](SECURITY.md))
- **Imperial Units** -- Reports, chat, and tool output use miles, mph, min/mile, feet, and lbs (the database and raw exports keep Garmin's native SI units)

## Installation

```bash
git clone https://github.com/jdellag/garmin-sync.git
cd garmin-sync
pip install -e .
```

**Requirements:** Python 3.10+

**Platform support:** macOS (primary), Windows 11 (fully supported). Linux works for all features except automatic scheduling (use crontab manually).

## Quick Start

```bash
# Interactive setup wizard (Garmin + OpenAI + training profile + HEVY)
garmin-sync setup

# Or set up manually
garmin-sync auth login            # Garmin OAuth
garmin-sync analyze configure     # OpenAI + training profile
garmin-sync hevy login            # Optional: HEVY strength tracking

# Sync and chat
garmin-sync sync all              # Sync last 30 days
garmin-sync analyze chat          # Talk to your AI coach
```

See [Getting Started](docs/getting-started.md) for a full walkthrough.

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, setup, first sync |
| [CLI Reference](docs/cli-reference.md) | All commands and flags |
| [AI Chat & Analysis](docs/ai-chat.md) | Interactive coaching, analysis reports, computed analytics |
| [MCP Integration](docs/mcp-integration.md) | Claude Desktop setup, 9 available tools |
| [HEVY Integration](docs/hevy-integration.md) | Strength training, volume tracking, set targets |
| [Configuration](docs/configuration.md) | TOML files, environment variables, data paths |
| [Scheduling](docs/scheduling.md) | Automatic daily sync (macOS/Windows) |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and fixes |

## Privacy & Security

- All data stored locally -- no third-party transmission except to APIs you configure (Garmin, HEVY, OpenAI)
- Config files are `0o600` (owner-only); directories are `0o700`
- HEVY-derived strings are sanitized before reaching the LLM
- `.gitignore` blocks `config.toml`, `*.fit`, `*.db`, `reports/`, `.env`

For a complete security overview, see [SECURITY.md](SECURITY.md).

## Development

```bash
pip install -e ".[dev]"
pytest                           # 733 tests
pytest --cov=garmin_sync         # With coverage
ruff check src/                  # Lint
```

## Disclaimer

This software is for **informational and educational purposes only**. It is not medical advice and should not be used as a substitute for professional medical guidance, diagnosis, or treatment. Always consult a qualified healthcare provider before making decisions about your health or training.

## License

This project is licensed under the [MIT License](LICENSE) — free to use, modify, and distribute, including commercially.

Copyright (c) 2026 James Della-Giustina.

## Acknowledgments

- [python-garminconnect](https://github.com/cyberjunky/python-garminconnect)
- [Garth](https://github.com/matin/garth)
- [Typer](https://typer.tiangolo.com/)
- [Rich](https://rich.readthedocs.io/)
- [FastMCP](https://github.com/jlowin/fastmcp)
