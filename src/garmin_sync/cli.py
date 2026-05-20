"""CLI commands for garmin-sync."""

from datetime import date, timedelta

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from garmin_sync import __version__
from garmin_sync.auth.garmin_auth import (
    AuthenticationError,
    get_auth_manager,
)
from garmin_sync.config import get_settings

app = typer.Typer(
    name="garmin-sync",
    help="Garmin Connect data sync and analysis tool",
    add_completion=True,
)

console = Console()

# Sub-command groups
auth_app = typer.Typer(help="Authentication commands")
sync_app = typer.Typer(help="Data synchronization")
report_app = typer.Typer(help="Generate reports")
stats_app = typer.Typer(help="Quick statistics")
schedule_app = typer.Typer(help="Manage automatic sync schedule")
analyze_app = typer.Typer(help="AI-powered fitness analysis")
hevy_app = typer.Typer(help="HEVY strength training integration")

mcp_app = typer.Typer(help="MCP server for Claude Code integration")

app.add_typer(auth_app, name="auth")
app.add_typer(sync_app, name="sync")
app.add_typer(report_app, name="report")
app.add_typer(stats_app, name="stats")
app.add_typer(schedule_app, name="schedule")
app.add_typer(analyze_app, name="analyze")
app.add_typer(hevy_app, name="hevy")
app.add_typer(mcp_app, name="mcp")


def version_callback(value: bool):
    if value:
        console.print(f"garmin-sync version {__version__}")
        raise typer.Exit()


def _get_database():
    """Get database instance, creating if needed."""
    from garmin_sync.db.database import Database

    settings = get_settings()
    settings.ensure_directories()

    db = Database(settings.database_path)
    db.initialize()
    db.migrate()
    return db


def _get_sync_manager():
    """Get configured sync manager."""
    from garmin_sync.sync.sync_manager import SyncManager

    db = _get_database()
    return SyncManager(db=db, console=console)


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit"
    ),
):
    """Garmin Connect data sync and analysis tool."""
    pass


# ==================== Auth Commands ====================

@auth_app.command("login")
def auth_login(
    email: str = typer.Option(None, "--email", "-e", help="Garmin account email"),
):
    """Interactive login to Garmin Connect."""
    settings = get_settings()
    auth = get_auth_manager(settings.garth_token_dir)

    # Prompt for credentials if not provided
    if not email:
        email = Prompt.ask("Enter your Garmin email")

    password = Prompt.ask("Enter your Garmin password", password=True)

    with console.status("Logging in to Garmin Connect..."):
        try:
            auth.login(email, password)
            console.print("[green]Successfully logged in![/green]")
            console.print(f"Tokens saved to: {settings.garth_token_dir}")
        except AuthenticationError as e:
            console.print(f"[red]Login failed: {e}[/red]")
            raise typer.Exit(1)


@auth_app.command("status")
def auth_status():
    """Check authentication status."""
    settings = get_settings()
    auth = get_auth_manager(settings.garth_token_dir)

    status = auth.get_status()

    table = Table(title="Authentication Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    auth_status_str = "[green]Yes[/green]" if status["authenticated"] else "[red]No[/red]"
    tokens_str = "[green]Yes[/green]" if status["has_tokens"] else "[yellow]No[/yellow]"

    table.add_row("Authenticated", auth_status_str)
    table.add_row("Tokens Exist", tokens_str)
    table.add_row("Token Directory", status["token_dir"])

    console.print(table)

    if not status["authenticated"]:
        if status["has_tokens"]:
            console.print("\n[yellow]Tokens exist but may be expired. Try 'garmin-sync auth login'[/yellow]")
        else:
            console.print("\n[yellow]Not logged in. Run 'garmin-sync auth login' to authenticate.[/yellow]")


@auth_app.command("logout")
def auth_logout(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Clear saved authentication tokens."""
    settings = get_settings()
    auth = get_auth_manager(settings.garth_token_dir)

    if not auth.has_tokens():
        console.print("[yellow]No tokens to remove.[/yellow]")
        return

    if not force:
        confirm = typer.confirm("Are you sure you want to logout?")
        if not confirm:
            console.print("Cancelled.")
            raise typer.Exit(0)

    auth.logout()
    console.print("[green]Successfully logged out. Tokens removed.[/green]")


# ==================== Sync Commands ====================

@sync_app.command("all")
def sync_all_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Days to sync"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-download existing data"),
    detailed: bool = typer.Option(False, "--detailed", help="Fetch full per-day data for rich reports (slower)"),
):
    """Sync all data types from Garmin Connect (and HEVY if configured)."""
    settings = get_settings()
    auth = get_auth_manager(settings.garth_token_dir)

    if not auth.has_tokens():
        console.print("[red]Not authenticated. Run 'garmin-sync auth login' first.[/red]")
        raise typer.Exit(1)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    console.print(f"Syncing data from {start_date} to {end_date}...")
    console.print()

    try:
        sync_manager = _get_sync_manager()
        results = sync_manager.sync_all(days=days, force=force, detailed=detailed)

        if detailed:
            console.print("[dim]Using detailed mode (per-day API calls)[/dim]\n")

        # Sync HEVY if configured and enabled
        hevy_result = None
        try:
            from garmin_sync.ai.config import load_config
            ai_config = load_config(settings.ai_config_path)

            if ai_config.hevy.is_configured() and ai_config.hevy.enabled:
                console.print("[dim]Syncing HEVY strength training data...[/dim]")
                hevy_sync_manager = _get_hevy_sync_manager()
                if hevy_sync_manager:
                    hevy_days = ai_config.hevy.sync_days or days
                    hevy_result = hevy_sync_manager.sync_workouts(days=hevy_days)
        except Exception as e:
            # HEVY errors shouldn't fail the whole sync
            console.print(f"[yellow]HEVY sync warning: {e}[/yellow]")

        # Display results
        console.print()
        table = Table(title="Sync Results")
        table.add_column("Data Type", style="cyan")
        table.add_column("Synced", justify="right")
        table.add_column("Skipped", justify="right")
        table.add_column("Status")

        for data_type, result in results.items():
            status = "[green]OK[/green]" if result.success else "[red]Errors[/red]"
            table.add_row(
                data_type,
                str(result.records_synced),
                str(result.records_skipped),
                status,
            )

        # Add HEVY result to table if synced
        if hevy_result:
            status = "[green]OK[/green]" if hevy_result.success else "[red]Errors[/red]"
            table.add_row(
                "hevy_workouts",
                str(hevy_result.records_synced),
                str(hevy_result.records_skipped),
                status,
            )

        console.print(table)

        # Show any errors
        all_errors = []
        for result in results.values():
            all_errors.extend(result.errors)
        if hevy_result:
            all_errors.extend(hevy_result.errors)

        if all_errors:
            console.print("\n[yellow]Errors encountered:[/yellow]")
            for error in all_errors[:5]:  # Show first 5 errors
                console.print(f"  - {error}")
            if len(all_errors) > 5:
                console.print(f"  ... and {len(all_errors) - 5} more")

        console.print(f"\n[green]Data saved to: {settings.database_path}[/green]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        console.print("Try running 'garmin-sync auth login' to re-authenticate.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Sync failed: {e}[/red]")
        raise typer.Exit(1)


@sync_app.command("activities")
def sync_activities_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Days to sync"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-download existing data"),
):
    """Sync activities only."""
    settings = get_settings()
    auth = get_auth_manager(settings.garth_token_dir)

    if not auth.has_tokens():
        console.print("[red]Not authenticated. Run 'garmin-sync auth login' first.[/red]")
        raise typer.Exit(1)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    console.print(f"Syncing activities from {start_date} to {end_date}...")

    try:
        sync_manager = _get_sync_manager()
        result = sync_manager.sync_activities(start_date, end_date, force=force)

        if result.success:
            console.print(f"[green]Synced {result.records_synced} activities[/green]")
            if result.records_skipped:
                console.print(f"  (skipped {result.records_skipped} existing)")
        else:
            console.print(f"[yellow]Synced with errors: {result.records_synced} activities[/yellow]")
            for error in result.errors:
                console.print(f"  - {error}")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


@sync_app.command("health")
def sync_health_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Days to sync"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-download existing data"),
    detailed: bool = typer.Option(False, "--detailed", help="Fetch full per-day data for rich reports (slower)"),
):
    """Sync health metrics only (sleep, HR, stress, HRV, body battery)."""
    settings = get_settings()
    auth = get_auth_manager(settings.garth_token_dir)

    if not auth.has_tokens():
        console.print("[red]Not authenticated. Run 'garmin-sync auth login' first.[/red]")
        raise typer.Exit(1)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    console.print(f"Syncing health metrics from {start_date} to {end_date}...")

    try:
        sync_manager = _get_sync_manager()

        health_syncs = [
            ("Daily Summary", sync_manager.sync_daily_summaries),
            ("Sleep", sync_manager.sync_sleep),
            ("Heart Rate", sync_manager.sync_heart_rate),
            ("Stress", sync_manager.sync_stress),
            ("HRV", sync_manager.sync_hrv),
            ("Body Battery", sync_manager.sync_body_battery),
        ]

        total_synced = 0
        for name, sync_func in health_syncs:
            with console.status(f"Syncing {name}..."):
                result = sync_func(start_date, end_date, force=force)
                total_synced += result.records_synced
                status = "[green]OK[/green]" if result.success else "[yellow]Errors[/yellow]"
                console.print(f"  {name}: {result.records_synced} records {status}")

        console.print(f"\n[green]Total: {total_synced} health records synced[/green]")

    except AuthenticationError as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


# ==================== Report Commands ====================

def _get_report_generator():
    """Get configured report generator."""
    from garmin_sync.reports.report_generator import ReportGenerator

    db = _get_database()
    return ReportGenerator(db)


@report_app.command("weekly")
def report_weekly_cmd(
    llm: bool = typer.Option(False, "--llm", help="Optimize for LLM context"),
    format: str = typer.Option("markdown", "--format", "-F", help="Output format (markdown or json)"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Generate weekly summary report."""
    import json

    try:
        generator = _get_report_generator()
        # JSON format always includes full data (implicitly llm_mode=True)
        report = generator.generate_weekly_report(llm_mode=llm, format=format)

        if format == "json":
            report_str = json.dumps(report, indent=2)
        else:
            report_str = report

        if output:
            from pathlib import Path
            output_path = Path(output)
            generator.save_report(report_str, output_path)
            console.print(f"[green]Report saved to: {output_path}[/green]")
        else:
            console.print(report_str)

    except Exception as e:
        console.print(f"[red]Error generating report: {e}[/red]")
        raise typer.Exit(1)


@report_app.command("monthly")
def report_monthly_cmd(
    year: int = typer.Option(None, "--year", "-y", help="Year (defaults to current)"),
    month: int = typer.Option(None, "--month", "-m", help="Month (defaults to current)"),
    llm: bool = typer.Option(False, "--llm", help="Optimize for LLM context"),
    format: str = typer.Option("markdown", "--format", "-F", help="Output format (markdown or json)"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Generate monthly summary report."""
    import json

    try:
        generator = _get_report_generator()
        # JSON format always includes full data (implicitly llm_mode=True)
        report = generator.generate_monthly_report(year=year, month=month, llm_mode=llm, format=format)

        if format == "json":
            report_str = json.dumps(report, indent=2)
        else:
            report_str = report

        if output:
            from pathlib import Path
            output_path = Path(output)
            generator.save_report(report_str, output_path)
            console.print(f"[green]Report saved to: {output_path}[/green]")
        else:
            console.print(report_str)

    except Exception as e:
        console.print(f"[red]Error generating report: {e}[/red]")
        raise typer.Exit(1)


# ==================== Export Commands ====================

export_app = typer.Typer(help="Export data")
app.add_typer(export_app, name="export")


@export_app.command("activities")
def export_activities_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Days to export"),
    format: str = typer.Option("json", "--format", "-f", help="Output format (json or csv)"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Export activities to JSON or CSV."""
    from pathlib import Path

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    settings = get_settings()
    default_ext = "json" if format == "json" else "csv"

    if output:
        output_path = Path(output)
    else:
        output_path = settings.exports_dir / f"activities_{end_date.isoformat()}.{default_ext}"

    try:
        generator = _get_report_generator()

        if format == "csv":
            count = generator.export_activities_csv(start_date, end_date, output_path)
        else:
            count = generator.export_activities_json(start_date, end_date, output_path)

        console.print(f"[green]Exported {count} activities to: {output_path}[/green]")

    except Exception as e:
        console.print(f"[red]Export failed: {e}[/red]")
        raise typer.Exit(1)


@export_app.command("health")
def export_health_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Days to export"),
    output: str = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Export health metrics to CSV."""
    from pathlib import Path

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    settings = get_settings()

    if output:
        output_path = Path(output)
    else:
        output_path = settings.exports_dir / f"health_{end_date.isoformat()}.csv"

    try:
        generator = _get_report_generator()
        count = generator.export_health_csv(start_date, end_date, output_path)
        console.print(f"[green]Exported {count} days of health data to: {output_path}[/green]")

    except Exception as e:
        console.print(f"[red]Export failed: {e}[/red]")
        raise typer.Exit(1)


# ==================== Stats Commands ====================

@stats_app.command("today")
def stats_today_cmd():
    """Show today's summary."""
    try:
        generator = _get_report_generator()
        report = generator.generate_today_stats()
        console.print(report)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@stats_app.command("week")
def stats_week_cmd():
    """Show this week's summary."""
    try:
        generator = _get_report_generator()
        report = generator.generate_week_stats()
        console.print(report)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


# ==================== Schedule Commands ====================


@schedule_app.command("install")
def schedule_install_cmd():
    """Install automatic daily sync (launchd on macOS, Task Scheduler on Windows)."""
    from garmin_sync.scheduler import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        console.print("[red]Automatic scheduling is not supported on this OS[/red]")
        console.print("For Linux, add to crontab manually:")
        console.print("  0 7 * * 1-5 garmin-sync sync all --days 1 --detailed")
        console.print("  0 10 * * 0,6 garmin-sync sync all --days 1 --detailed")
        raise typer.Exit(1)

    settings = get_settings()

    # Verify authentication before installing
    auth = get_auth_manager(settings.garth_token_dir)
    if not auth.has_tokens():
        console.print("[red]Not authenticated. Run 'garmin-sync auth login' first.[/red]")
        raise typer.Exit(1)

    success, message = scheduler.install(settings.logs_dir)

    if success:
        console.print(f"[green]{message}[/green]")
        console.print()
        console.print("Schedule:")
        console.print("  Weekdays (Mon-Fri): 7:00 AM")
        console.print("  Weekends (Sat-Sun): 10:00 AM")
        console.print()
        console.print(f"Logs: {settings.logs_dir}")
        console.print()
        console.print("Commands:")
        console.print("  garmin-sync schedule status  - Check status")
        console.print("  garmin-sync schedule logs    - View recent logs")
        console.print("  garmin-sync schedule uninstall - Remove schedule")
    else:
        console.print(f"[red]{message}[/red]")
        raise typer.Exit(1)


@schedule_app.command("uninstall")
def schedule_uninstall_cmd():
    """Remove automatic sync schedule."""
    from garmin_sync.scheduler import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        console.print("[yellow]Manual crontab removal required on Linux[/yellow]")
        raise typer.Exit(0)

    success, message = scheduler.uninstall()

    if success:
        console.print(f"[green]{message}[/green]")
    else:
        console.print(f"[red]{message}[/red]")
        raise typer.Exit(1)


@schedule_app.command("status")
def schedule_status_cmd():
    """Show automatic sync schedule status."""
    from garmin_sync.scheduler import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        console.print("[yellow]Automatic scheduling is not supported on this OS[/yellow]")
        console.print("For Linux, add to crontab manually.")
        raise typer.Exit(0)

    status = scheduler.get_status()
    settings = get_settings()

    table = Table(title="Sync Schedule Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    installed_str = "[green]Yes[/green]" if status["installed"] else "[red]No[/red]"
    loaded_str = "[green]Yes[/green]" if status["loaded"] else "[yellow]No[/yellow]"

    table.add_row("Installed", installed_str)
    table.add_row("Loaded", loaded_str)

    if status["schedule"]:
        table.add_row("Weekday Time", status["schedule"]["weekday_time"] or "N/A")
        table.add_row("Weekend Time", status["schedule"]["weekend_time"] or "N/A")

    # Show platform-specific details
    if "plist_path" in status:
        table.add_row("Plist Path", status["plist_path"])
    if "tasks" in status:
        for label, info in status.get("tasks", {}).items():
            table.add_row(
                f"Task ({label})",
                f"{info.get('status', 'Unknown')} — next: {info.get('next_run', 'N/A')}",
            )

    table.add_row("Log Directory", str(settings.logs_dir))

    console.print(table)

    # Show last sync from log if available
    log_file = settings.logs_dir / "sync.log"
    if log_file.exists():
        console.print()
        console.print("[dim]Last log entries:[/dim]")
        try:
            lines = log_file.read_text().strip().split("\n")
            for line in lines[-5:]:
                console.print(f"  {line}")
        except Exception:
            pass


@schedule_app.command("logs")
def schedule_logs_cmd(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    errors: bool = typer.Option(False, "--errors", "-e", help="Show error log instead"),
):
    """View sync logs."""
    settings = get_settings()

    log_file = settings.logs_dir / ("sync-error.log" if errors else "sync.log")

    if not log_file.exists():
        console.print(f"[yellow]No log file found at {log_file}[/yellow]")
        console.print("Logs will be created after the first scheduled sync runs.")
        raise typer.Exit(0)

    try:
        content = log_file.read_text().strip().split("\n")
        for line in content[-lines:]:
            console.print(line)
    except Exception as e:
        console.print(f"[red]Error reading log: {e}[/red]")
        raise typer.Exit(1)


# ==================== Analyze Commands ====================


def _get_today_activities_summary() -> str:
    """Get a summary of activities completed today.

    Returns:
        String summary like "Morning: 5km easy run (45 min)" or "none"
    """
    from garmin_sync.db.database import Database
    from garmin_sync.db.repository import Repository

    settings = get_settings()
    db = Database(settings.database_path)
    db.initialize()
    repo = Repository(db)

    today = date.today().isoformat()
    activities = repo.get_activities(start_date=today, end_date=today + "T23:59:59")

    if not activities:
        return "none"

    summaries = []
    for act in activities:
        parts = []
        if act.activity_name:
            parts.append(act.activity_name)
        elif act.activity_type:
            parts.append(act.activity_type)
        else:
            parts.append("Activity")

        if act.distance_meters:
            km = act.distance_meters / 1000
            parts.append(f"({km:.1f} km)")

        if act.duration_seconds:
            mins = int(act.duration_seconds / 60)
            parts.append(f"{mins} min")

        summaries.append(" ".join(parts))

    return "; ".join(summaries)


def _run_analysis() -> tuple[bool, str, str]:
    """Run AI analysis on fitness data.

    Returns:
        Tuple of (success, analysis_text, output_path)
    """
    from datetime import timedelta

    from garmin_sync.ai import (
        analyze_fitness_data,
        build_analysis_prompt,
        generate_baseline_summary,
        generate_detailed_7d,
        load_config,
    )

    settings = get_settings()
    settings.ensure_directories()

    # Load AI config
    ai_config = load_config(settings.ai_config_path)

    if not ai_config.is_configured():
        return False, "AI not configured. Run 'garmin-sync analyze configure' first.", ""

    if not ai_config.enabled:
        return False, "AI analysis is disabled in configuration.", ""

    # Get report generator and generate JSON data
    try:
        generator = _get_report_generator()
        weekly_json = generator.generate_weekly_report(format="json")
    except Exception as e:
        return False, f"Failed to generate report data: {e}", ""

    # Build baseline and detailed data
    baseline_30d = generate_baseline_summary(weekly_json)
    detailed_7d = generate_detailed_7d(weekly_json)

    # Load previous analyses for context (last 7 days)
    previous_analyses = []
    today = date.today()
    for i in range(7, 0, -1):  # Oldest first
        report_date = today - timedelta(days=i)
        report_path = settings.reports_dir / f"analysis-{report_date.isoformat()}.md"
        if report_path.exists():
            try:
                previous_analyses.append(report_path.read_text())
            except Exception:
                pass  # Skip unreadable files

    # Get today's completed activities for template
    completed_today = _get_today_activities_summary()

    # Get strength training data if HEVY is configured
    strength_data = None
    if ai_config.hevy.is_configured() and ai_config.hevy.enabled:
        try:
            from garmin_sync.reports.aggregators import DataAggregator
            db = _get_database()
            aggregator = DataAggregator(db)
            strength_data = aggregator.get_strength_volume_summary(days=7)
        except Exception:
            pass  # Strength data is optional

    # Build prompt
    prompt = build_analysis_prompt(
        baseline_30d=baseline_30d,
        detailed_7d=detailed_7d,
        current_date=today,
        user_schedule=ai_config.schedule,
        user_context=ai_config.user_context,
        previous_analyses=previous_analyses if previous_analyses else None,
        timezone=ai_config.timezone,
        completed_today=completed_today,
        strength_data=strength_data,
    )

    # Call OpenAI
    try:
        analysis = analyze_fitness_data(
            prompt=prompt,
            api_key=ai_config.api_key,
            model=ai_config.model,
        )
    except Exception as e:
        return False, f"OpenAI analysis failed: {e}", ""

    # Format and save report
    today = date.today()
    report_content = f"""# Fitness Analysis - {today.strftime('%A, %B %d, %Y')}

{analysis}

---
*Generated by garmin-sync AI analysis using {ai_config.model}*
"""

    output_path = settings.reports_dir / f"analysis-{today.isoformat()}.md"
    output_path.write_text(report_content)

    return True, analysis, str(output_path)


@analyze_app.callback(invoke_without_command=True)
def analyze_default(ctx: typer.Context):
    """Run AI analysis on recent fitness data."""
    if ctx.invoked_subcommand is not None:
        return

    with console.status("Running AI analysis..."):
        success, result, output_path = _run_analysis()

    if success:
        console.print(f"[green]Analysis complete![/green]")
        console.print(f"Saved to: {output_path}")
        console.print()
        console.print(result)
    else:
        console.print(f"[red]{result}[/red]")
        raise typer.Exit(1)


def _earliest_available_year(default: int = 2021) -> int:
    """Earliest year present in sleep_daily, falling back to `default`."""
    try:
        db = _get_database()
        cursor = db.connection.cursor()
        cursor.execute("SELECT MIN(date) AS d FROM sleep_daily")
        row = cursor.fetchone()
        if row and row["d"]:
            return int(row["d"][:4])
    except Exception:
        pass
    return default


def _run_longitudinal_analysis(
    start_year: int,
    end_year: int,
    granularity: str,
) -> tuple[bool, str, str]:
    """Run multi-year longitudinal AI review. Returns (success, text, output_path)."""
    from garmin_sync.ai import (
        LONGITUDINAL_SYSTEM_MESSAGE,
        analyze_fitness_data,
        build_longitudinal_prompt,
        load_config,
    )
    from garmin_sync.reports.aggregators import DataAggregator

    settings = get_settings()
    settings.ensure_directories()
    ai_config = load_config(settings.ai_config_path)

    if not ai_config.is_configured():
        return False, "AI not configured. Run 'garmin-sync analyze configure' first.", ""
    if not ai_config.enabled:
        return False, "AI analysis is disabled in configuration.", ""

    db = _get_database()
    aggregator = DataAggregator(db)

    longitudinal_data = {
        "aerobic_efficiency": aggregator.get_aerobic_efficiency_by_period(
            start_year, end_year, granularity
        ),
        "health_baselines": aggregator.get_yearly_health_baselines(start_year, end_year),
        "volume": aggregator.get_volume_by_period(start_year, end_year, granularity),
        "hr_drift": aggregator.get_hr_drift_by_period(start_year, end_year),
    }

    strength: dict = {}
    if ai_config.hevy.is_configured() and ai_config.hevy.enabled:
        for lift in ("bench_press", "squat", "deadlift", "overhead_press"):
            try:
                prog = aggregator.get_strength_exercise_progression(
                    lift, days=365 * 5
                )
                if prog and prog.get("sessions"):
                    strength[lift] = prog
            except Exception:
                continue
    longitudinal_data["strength"] = strength

    today = date.today()
    prompt = build_longitudinal_prompt(
        longitudinal_data=longitudinal_data,
        current_date=today,
        user_context=ai_config.user_context or "",
        granularity=granularity,
    )

    try:
        analysis = analyze_fitness_data(
            prompt=prompt,
            api_key=ai_config.api_key,
            model=ai_config.model,
            system_message=LONGITUDINAL_SYSTEM_MESSAGE,
        )
    except Exception as e:
        return False, f"OpenAI analysis failed: {e}", ""

    report_content = (
        f"# Longitudinal Fitness Review — {today.strftime('%A, %B %d, %Y')}\n"
        f"*Years: {start_year}-{end_year} · Granularity: {granularity}*\n\n"
        f"{analysis}\n\n"
        f"---\n"
        f"*Generated by garmin-sync longitudinal analysis using {ai_config.model}*\n"
    )

    output_path = settings.reports_dir / f"longitudinal-{today.isoformat()}.md"
    output_path.write_text(report_content)
    try:
        output_path.chmod(0o600)
    except OSError:
        pass

    return True, analysis, str(output_path)


@analyze_app.command("longitudinal")
def analyze_longitudinal_cmd(
    start_year: int = typer.Option(
        None, "--start-year", help="First year to include (default: earliest in sleep_daily)"
    ),
    end_year: int = typer.Option(
        None, "--end-year", help="Last year to include (default: current year)"
    ),
    granularity: str = typer.Option(
        "year", "--granularity", "-g", help="Bucket size: year or quarter"
    ),
):
    """Run a multi-year fitness review. Saves a markdown report alongside the daily ones."""
    if granularity not in ("year", "quarter"):
        console.print("[red]--granularity must be 'year' or 'quarter'[/red]")
        raise typer.Exit(2)

    today = date.today()
    sy = start_year if start_year is not None else _earliest_available_year()
    ey = end_year if end_year is not None else today.year
    if sy > ey:
        console.print(f"[red]start-year ({sy}) must be <= end-year ({ey})[/red]")
        raise typer.Exit(2)

    with console.status(f"Running longitudinal analysis {sy}-{ey} ({granularity})..."):
        success, result, output_path = _run_longitudinal_analysis(sy, ey, granularity)

    if success:
        console.print(f"[green]Longitudinal review complete![/green]")
        console.print(f"Saved to: {output_path}")
        console.print()
        console.print(result)
    else:
        console.print(f"[red]{result}[/red]")
        raise typer.Exit(1)


@analyze_app.command("configure")
def analyze_configure():
    """Configure AI analysis settings (API key, schedule, etc.)."""
    from garmin_sync.ai import AIConfig, load_config, save_config

    settings = get_settings()
    current_config = load_config(settings.ai_config_path)

    console.print("[bold]AI Analysis Configuration[/bold]")
    console.print()

    # API Key
    if current_config.api_key:
        masked_key = current_config.api_key[:8] + "..." + current_config.api_key[-4:]
        console.print(f"Current API key: {masked_key}")
        update_key = typer.confirm("Update API key?", default=False)
    else:
        update_key = True

    if update_key:
        api_key = Prompt.ask("Enter your OpenAI API key", password=True)
        current_config.api_key = api_key

    # Model
    console.print(f"\nCurrent model: {current_config.model}")
    model = Prompt.ask(
        "Model to use",
        default=current_config.model,
        choices=["o3-mini", "gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    )
    current_config.model = model

    # Enabled
    current_config.enabled = typer.confirm(
        "Enable automatic analysis after sync?",
        default=current_config.enabled,
    )

    # Schedule
    console.print("\n[bold]Weekly Training Schedule[/bold]")
    console.print("This helps the AI understand your typical week.")
    console.print(f"Current schedule:\n{current_config.schedule}")
    if typer.confirm("\nUpdate schedule?", default=False):
        console.print("Enter your weekly schedule (press Enter twice when done):")
        lines = []
        while True:
            line = Prompt.ask("", default="")
            if not line:
                break
            lines.append(line)
        if lines:
            current_config.schedule = "\n".join(lines)

    # User context
    console.print(f"\nCurrent context: {current_config.user_context or '(none)'}")
    if typer.confirm("Update training context/goals?", default=False):
        context = Prompt.ask("Enter your training context (goals, focus areas, etc.)")
        current_config.user_context = context

    # Save
    save_config(current_config, settings.ai_config_path)
    console.print(f"\n[green]Configuration saved to: {settings.ai_config_path}[/green]")


@analyze_app.command("view")
def analyze_view(
    date_str: str = typer.Option(None, "--date", "-d", help="View analysis for specific date (YYYY-MM-DD)"),
    lines: int = typer.Option(0, "--lines", "-n", help="Show only last N lines (0 for all)"),
):
    """View recent AI analysis."""
    from pathlib import Path

    settings = get_settings()
    reports_dir = settings.reports_dir

    if not reports_dir.exists():
        console.print("[yellow]No analysis reports found.[/yellow]")
        console.print("Run 'garmin-sync analyze' to generate one.")
        raise typer.Exit(0)

    if date_str:
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            console.print("[red]Invalid date format. Use YYYY-MM-DD.[/red]")
            raise typer.Exit(1)
        # View specific date
        report_path = reports_dir / f"analysis-{date_str}.md"
        if not report_path.exists():
            console.print(f"[yellow]No analysis found for {date_str}[/yellow]")
            raise typer.Exit(1)
    else:
        # Find most recent report
        reports = sorted(reports_dir.glob("analysis-*.md"), reverse=True)
        if not reports:
            console.print("[yellow]No analysis reports found.[/yellow]")
            console.print("Run 'garmin-sync analyze' to generate one.")
            raise typer.Exit(0)
        report_path = reports[0]

    content = report_path.read_text()

    if lines > 0:
        content_lines = content.split("\n")
        content = "\n".join(content_lines[-lines:])

    console.print(content)
    console.print(f"\n[dim]Report: {report_path}[/dim]")


@analyze_app.command("list")
def analyze_list(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of reports to list"),
):
    """List available analysis reports."""
    settings = get_settings()
    reports_dir = settings.reports_dir

    if not reports_dir.exists():
        console.print("[yellow]No analysis reports found.[/yellow]")
        raise typer.Exit(0)

    reports = sorted(reports_dir.glob("analysis-*.md"), reverse=True)

    if not reports:
        console.print("[yellow]No analysis reports found.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Analysis Reports")
    table.add_column("Date", style="cyan")
    table.add_column("Size")
    table.add_column("Path", style="dim")

    for report in reports[:limit]:
        # Extract date from filename
        report_date = report.stem.replace("analysis-", "")
        size = f"{report.stat().st_size:,} bytes"
        table.add_row(report_date, size, str(report))

    console.print(table)

    if len(reports) > limit:
        console.print(f"\n[dim]Showing {limit} of {len(reports)} reports[/dim]")


@analyze_app.command("chat")
def analyze_chat():
    """Start interactive chat with AI coach."""
    from garmin_sync.ai import ChatSession, OpenAIAnalysisError, load_config
    from garmin_sync.db.database import Database
    from garmin_sync.db.repository import Repository

    settings = get_settings()
    ai_config = load_config(settings.ai_config_path)

    if not ai_config.is_configured():
        console.print("[red]AI not configured.[/red]")
        console.print("Run 'garmin-sync analyze configure' first to set your API key.")
        raise typer.Exit(1)

    if not ai_config.enabled:
        console.print("[yellow]AI analysis is disabled in configuration.[/yellow]")
        raise typer.Exit(1)

    # Initialize database and repository
    db = Database(settings.database_path)
    db.initialize()
    db.migrate()
    repo = Repository(db)

    # Create chat session
    session = ChatSession(
        repository=repo,
        ai_config=ai_config,
        reports_dir=settings.reports_dir,
    )

    # Print welcome message with context summary
    context = session.get_context_summary()
    console.print()
    console.print("[bold cyan]AI Fitness Coach[/bold cyan]")
    console.print("[dim]─" * 40 + "[/dim]")
    console.print(f"  Analyses loaded: {context['analysis_count']} (last 7 days)")
    console.print(f"  Chat history: {context['chat_message_count']} messages")
    tools_status = f"[green]ON[/green] ({context['tool_count']} tools)" if context['tools_enabled'] else "[yellow]OFF[/yellow]"
    console.print(f"  Tools: {tools_status}")
    model_str = "gpt-5.4 (tools)" if context['tools_enabled'] else ai_config.model
    console.print(f"  Model: {model_str}")
    console.print("[dim]─" * 40 + "[/dim]")
    console.print()
    console.print("[dim]Commands: /quit, /clear, /context, /tools[/dim]")
    console.print()

    # Interactive loop
    while True:
        try:
            user_input = console.input("[bold green]You:[/bold green] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Handle special commands
        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("Goodbye!")
            break

        if user_input.lower() == "/clear":
            count = session.clear_history()
            console.print(f"[yellow]Cleared {count} messages from history.[/yellow]")
            continue

        if user_input.lower() == "/context":
            ctx = session.get_context_summary()
            console.print()
            console.print("[bold]Current Context:[/bold]")
            console.print(f"  Analyses: {ctx['analysis_count']}")
            if ctx['analysis_dates']:
                console.print(f"    Dates: {', '.join(ctx['analysis_dates'])}")
            console.print(f"  Chat messages: {ctx['chat_message_count']}")
            console.print(f"  Est. tokens: {ctx['estimated_tokens']:,} / {ctx['token_budget']:,}")
            tools_status = f"ON ({ctx['tool_count']} tools)" if ctx['tools_enabled'] else "OFF"
            console.print(f"  Tools: {tools_status}")
            console.print()
            continue

        if user_input.lower() == "/tools":
            session.use_tools = not session.use_tools
            status = "[green]ON[/green]" if session.use_tools else "[yellow]OFF[/yellow]"
            model_info = " (using gpt-5.4)" if session.use_tools else f" (using {ai_config.model})"
            console.print(f"[yellow]Tool calling: {status}{model_info}[/yellow]")
            continue

        # Send message to AI
        try:
            with console.status("[dim]Thinking...[/dim]"):
                response = session.send_message(user_input)

            console.print()
            console.print("[bold blue]Coach:[/bold blue]", response)
            console.print()

        except OpenAIAnalysisError as e:
            console.print(f"[red]Error: {e}[/red]")
            continue


# ==================== HEVY Commands ====================


def _get_hevy_client():
    """Get configured HEVY client."""
    from garmin_sync.ai import load_config
    from garmin_sync.hevy import HevyClient

    settings = get_settings()
    ai_config = load_config(settings.ai_config_path)

    if not ai_config.hevy.is_configured():
        return None

    return HevyClient(ai_config.hevy.api_key)


def _get_hevy_sync_manager():
    """Get configured HEVY sync manager."""
    from garmin_sync.hevy import HevySyncManager

    client = _get_hevy_client()
    if client is None:
        return None

    db = _get_database()
    from garmin_sync.db.repository import Repository
    repo = Repository(db)

    return HevySyncManager(client=client, repository=repo)


@hevy_app.command("login")
def hevy_login():
    """Configure HEVY API key."""
    from garmin_sync.ai import load_config, save_config

    settings = get_settings()
    current_config = load_config(settings.ai_config_path)

    console.print("[bold]HEVY Configuration[/bold]")
    console.print()
    console.print("Get your API key from: [link=https://hevy.com/settings?developer]https://hevy.com/settings?developer[/link]")
    console.print("[dim]Note: Requires HEVY Pro subscription[/dim]")
    console.print()

    if current_config.hevy.api_key:
        masked_key = current_config.hevy.api_key[:8] + "..." + current_config.hevy.api_key[-4:]
        console.print(f"Current API key: {masked_key}")
        update_key = typer.confirm("Update API key?", default=False)
    else:
        update_key = True

    if update_key:
        api_key = Prompt.ask("Enter your HEVY API key", password=True)
        current_config.hevy.api_key = api_key

    current_config.hevy.enabled = typer.confirm(
        "Enable HEVY sync?",
        default=current_config.hevy.enabled,
    )

    save_config(current_config, settings.ai_config_path)
    console.print(f"\n[green]Configuration saved to: {settings.ai_config_path}[/green]")

    # Test connection
    if current_config.hevy.is_configured():
        with console.status("Testing HEVY connection..."):
            try:
                from garmin_sync.hevy import HevyClient
                client = HevyClient(current_config.hevy.api_key)
                count_data = client.get_workout_count()
                workout_count = count_data.get("workout_count", 0)
                console.print(f"[green]Connected! Found {workout_count} workouts in HEVY.[/green]")
            except Exception as e:
                console.print(f"[red]Connection failed: {e}[/red]")


@hevy_app.command("sync")
def hevy_sync(
    days: int = typer.Option(30, "--days", "-d", help="Days of workouts to sync"),
):
    """Sync HEVY workouts to local database."""
    from garmin_sync.ai import load_config

    settings = get_settings()
    ai_config = load_config(settings.ai_config_path)

    if not ai_config.hevy.is_configured():
        console.print("[red]HEVY not configured.[/red]")
        console.print("Run 'garmin-sync hevy login' first to set your API key.")
        raise typer.Exit(1)

    if not ai_config.hevy.enabled:
        console.print("[yellow]HEVY sync is disabled in configuration.[/yellow]")
        raise typer.Exit(0)

    console.print(f"Syncing HEVY workouts from last {days} days...")

    try:
        sync_manager = _get_hevy_sync_manager()
        if sync_manager is None:
            console.print("[red]Failed to create HEVY sync manager.[/red]")
            raise typer.Exit(1)

        with console.status("Syncing workouts..."):
            results = sync_manager.sync_all(days=days)

        # Display results
        table = Table(title="HEVY Sync Results")
        table.add_column("Data Type", style="cyan")
        table.add_column("Synced", justify="right")
        table.add_column("Skipped", justify="right")
        table.add_column("Status")

        for data_type, result in results.items():
            status = "[green]OK[/green]" if result.success else "[red]Errors[/red]"
            table.add_row(
                data_type,
                str(result.records_synced),
                str(result.records_skipped),
                status,
            )

        console.print(table)

        # Show any errors
        all_errors = []
        for result in results.values():
            all_errors.extend(result.errors)

        if all_errors:
            console.print("\n[yellow]Errors encountered:[/yellow]")
            for error in all_errors[:5]:
                console.print(f"  - {error}")

    except Exception as e:
        console.print(f"[red]Sync failed: {e}[/red]")
        raise typer.Exit(1)


@hevy_app.command("status")
def hevy_status():
    """Show HEVY sync status and recent workouts."""
    from garmin_sync.ai import load_config
    from garmin_sync.db.database import Database
    from garmin_sync.db.repository import Repository

    settings = get_settings()
    ai_config = load_config(settings.ai_config_path)

    # Configuration status
    table = Table(title="HEVY Configuration")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    configured = "[green]Yes[/green]" if ai_config.hevy.is_configured() else "[red]No[/red]"
    enabled = "[green]Yes[/green]" if ai_config.hevy.enabled else "[yellow]No[/yellow]"

    table.add_row("Configured", configured)
    table.add_row("Enabled", enabled)
    table.add_row("Sync Days", str(ai_config.hevy.sync_days))

    console.print(table)

    if not ai_config.hevy.is_configured():
        console.print("\n[yellow]Run 'garmin-sync hevy login' to configure.[/yellow]")
        return

    # Database stats
    db = Database(settings.database_path)
    db.initialize()
    db.migrate()
    repo = Repository(db)

    console.print()

    # Recent workouts
    recent_workouts = repo.get_hevy_workouts(limit=5)
    if recent_workouts:
        workout_table = Table(title="Recent Workouts")
        workout_table.add_column("Date", style="cyan")
        workout_table.add_column("Title")
        workout_table.add_column("Volume (lbs)", justify="right")
        workout_table.add_column("Sets", justify="right")

        for w in recent_workouts:
            workout_date = w["start_time"][:10] if w["start_time"] else "N/A"
            volume_lbs = (w["volume_kg"] or 0) * 2.20462
            volume = f"{volume_lbs:,.0f}" if volume_lbs else "-"
            sets = str(w["set_count"]) if w["set_count"] else "-"
            workout_table.add_row(workout_date, w["title"] or "Untitled", volume, sets)

        console.print(workout_table)
    else:
        console.print("[dim]No workouts synced yet.[/dim]")


KG_TO_LBS = 2.20462


@hevy_app.command("volume")
def hevy_volume(
    days: int = typer.Option(7, "--days", "-d", help="Days to aggregate"),
):
    """Show training volume by muscle group."""
    from garmin_sync.db.database import Database
    from garmin_sync.db.repository import Repository

    settings = get_settings()
    db = Database(settings.database_path)
    db.initialize()
    db.migrate()
    repo = Repository(db)

    # Get workout count
    workout_count = repo.get_hevy_workout_count(days=days)

    if workout_count == 0:
        console.print(f"[yellow]No HEVY workouts found in the last {days} days.[/yellow]")
        console.print("Run 'garmin-sync hevy sync' to sync your workouts.")
        raise typer.Exit(0)

    console.print(f"\n[bold]Training Volume - Last {days} Days[/bold]")
    console.print(f"Workouts: {workout_count}\n")

    # Get volume by muscle group
    volume_data = repo.get_hevy_volume_by_muscle_group(days=days)

    if not volume_data:
        console.print("[dim]No volume data available.[/dim]")
        return

    table = Table()
    table.add_column("Muscle Group", style="cyan")
    table.add_column("Volume (lbs)", justify="right")
    table.add_column("Sets", justify="right")
    table.add_column("Reps", justify="right")

    total_volume = 0
    total_sets = 0
    total_reps = 0

    for group, data in sorted(volume_data.items(), key=lambda x: x[1]["volume_kg"], reverse=True):
        volume_lbs = (data["volume_kg"] or 0) * KG_TO_LBS
        volume_str = f"{volume_lbs:,.0f}" if volume_lbs else "-"
        table.add_row(
            group.title() if group else "Other",
            volume_str,
            str(data["sets"]),
            str(data["reps"]),
        )
        total_volume += volume_lbs
        total_sets += data["sets"] or 0
        total_reps += data["reps"] or 0

    # Add total row
    table.add_row("─" * 15, "─" * 10, "─" * 5, "─" * 5)
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{total_volume:,.0f}[/bold]",
        f"[bold]{total_sets}[/bold]",
        f"[bold]{total_reps}[/bold]",
    )

    console.print(table)


# ==================== MCP Commands ====================


@mcp_app.command("serve")
def mcp_serve():
    """Start MCP server for Claude Code.

    Add to Claude Code with:
        claude mcp add garmin-sync -- garmin-sync mcp serve
    """
    from garmin_sync.mcp.server import main as mcp_main

    mcp_main()


@mcp_app.command("info")
def mcp_info():
    """Show available MCP tools."""
    console.print("[bold]garmin-sync MCP Server[/bold]\n")
    console.print("Tools:")
    console.print("  get_recent_activities      - Garmin activities with metrics")
    console.print("  get_recovery_status        - HRV, sleep, body battery, RHR")
    console.print("  get_training_load_analysis - Acute:chronic ratio analysis")
    console.print("  get_strength_training_summary - HEVY volume by muscle group")
    console.print("  get_exercise_progression   - Track 1RM for specific exercises")
    console.print("  get_workout_details        - Detailed workouts with sets")
    console.print("  get_weekly_comparison      - This week vs last week")
    console.print("  get_longitudinal_summary   - Multi-year aerobic efficiency, baselines, volume")
    console.print("  sync_garmin_data           - Pull latest data from Garmin\n")
    console.print("Add to Claude Code:")
    console.print("  [green]claude mcp add garmin-sync -- garmin-sync mcp serve[/green]")


if __name__ == "__main__":
    app()
