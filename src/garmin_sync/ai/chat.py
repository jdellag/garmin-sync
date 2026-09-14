"""Chat session manager for interactive AI conversations."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from garmin_sync import temporal
from garmin_sync.ai.config import AIConfig
from garmin_sync.ai.openai_client import (
    COACH_SYSTEM_MESSAGE,
    COACH_SYSTEM_MESSAGE_WITH_TOOLS,
    OpenAIAnalysisError,
    chat_with_history,
    chat_with_tools,
)
from garmin_sync.ai.prompt_builder import process_template, safe_user_string
from garmin_sync.ai.report_history import summarize_decisions
from garmin_sync.ai.tools import TOOLS
from garmin_sync.db.repository import Repository
from garmin_sync.reports.aggregators import DataAggregator
from garmin_sync.tools.executor import ToolExecutor
from garmin_sync.units import (
    meters_to_feet,
    meters_to_miles,
    mps_to_mph,
    pace_sec_per_mile,
)


@dataclass
class DataFingerprint:
    """Fingerprint to detect when underlying data has changed."""

    last_sync_timestamp: str | None
    analysis_file_mtimes: dict[str, float]  # {filepath: mtime}
    hevy_workout_count: int
    local_date: str | None = None  # relative day labels go stale at midnight


@dataclass
class CachedChatContext:
    """Cached system message (persona + reference data) for the session."""

    system_message: str
    cache_timestamp: datetime
    data_fingerprint: DataFingerprint
    token_count: int


class ChatSession:
    """Manages interactive chat with conversation history."""

    # Token budget limits
    MAX_CONTEXT_TOKENS = 100_000  # Conservative limit for most models
    RESPONSE_RESERVE = 20_000  # Reserve for response generation
    CONTEXT_BUDGET = MAX_CONTEXT_TOKENS - RESPONSE_RESERVE

    # Days of saved daily analyses preloaded into context, counting today.
    # Deliberately small: the reports are the model's own prior output, and
    # tools fetch anything older on demand.
    ANALYSES_CONTEXT_DAYS = 2

    # Stored chat messages carried into each API call. History persists across
    # sessions in the DB; a large carryover makes weeks-old conversations
    # bleed into new ones. /clear wipes it entirely.
    CHAT_HISTORY_LIMIT = 30

    # A longer gap between messages, or a change of local date, starts a new
    # session. Sessions never span midnight, so "today" inside one has a
    # single meaning.
    SESSION_GAP = timedelta(hours=2)

    def __init__(
        self,
        repository: Repository,
        ai_config: AIConfig,
        reports_dir: Path,
        use_tools: bool | None = None,
    ):
        """Initialize chat session.

        Args:
            repository: Database repository for chat history
            ai_config: AI configuration (API key, model, etc.)
            reports_dir: Directory containing analysis report files
            use_tools: Enable tool calling (defaults to ai_config.use_tools)
        """
        self.repo = repository
        self.config = ai_config
        self.reports_dir = reports_dir
        self._cached_context: CachedChatContext | None = None
        self._use_tools = use_tools if use_tools is not None else ai_config.use_tools
        self._tool_executor: ToolExecutor | None = None

    @property
    def use_tools(self) -> bool:
        """Whether tool calling is enabled."""
        return self._use_tools

    @use_tools.setter
    def use_tools(self, value: bool) -> None:
        """Toggle tool calling on/off."""
        self._use_tools = value
        # Invalidate cache when toggling tools (system message changes)
        self._cached_context = None

    @property
    def tool_executor(self) -> ToolExecutor:
        """Lazy-initialize tool executor."""
        if self._tool_executor is None:
            aggregator = DataAggregator(self.repo.db)
            self._tool_executor = ToolExecutor(self.repo, aggregator)
        return self._tool_executor

    def _now(self) -> datetime:
        """Current time in the configured timezone."""
        return temporal.now(self.config.timezone)

    def _today(self) -> date:
        return self._now().date()

    def get_historical_analyses(self, days: int = 7) -> list[dict]:
        """Load analysis reports from the last N days, including today's.

        Args:
            days: Number of days to cover, counting today

        Returns:
            List of dicts with 'date' and 'content' keys, oldest first
        """
        analyses = []
        today = self._today()

        for i in range(days - 1, -1, -1):  # Oldest first, ending with today
            report_date = today - timedelta(days=i)
            report_path = self.reports_dir / f"analysis-{report_date.isoformat()}.md"

            if report_path.exists():
                try:
                    content = report_path.read_text()
                    analyses.append({
                        "date": report_date.isoformat(),
                        "content": content,
                    })
                except Exception:
                    pass  # Skip unreadable files

        return analyses

    def _get_data_fingerprint(self) -> DataFingerprint:
        """Generate fingerprint of current data state.

        The fingerprint captures the state of underlying data sources
        to detect when the cache should be invalidated.

        Returns:
            DataFingerprint with current sync timestamp, analysis file mtimes,
            HEVY workout count, and the local date
        """
        last_sync = self.repo.get_latest_sync_timestamp()

        analysis_mtimes: dict[str, float] = {}
        today = self._today()
        for i in range(self.ANALYSES_CONTEXT_DAYS - 1, -1, -1):
            report_date = today - timedelta(days=i)
            report_path = self.reports_dir / f"analysis-{report_date.isoformat()}.md"
            if report_path.exists():
                analysis_mtimes[str(report_path)] = report_path.stat().st_mtime

        hevy_count = self.repo.get_hevy_workout_count(days=7)

        return DataFingerprint(
            last_sync_timestamp=last_sync,
            analysis_file_mtimes=analysis_mtimes,
            hevy_workout_count=hevy_count,
            local_date=today.isoformat(),
        )

    def _is_cache_valid(self) -> bool:
        """Check if cached context is still valid.

        Compares the current data fingerprint against the cached fingerprint
        to determine if any underlying data has changed.

        Returns:
            True if cache is valid and can be reused, False otherwise
        """
        if self._cached_context is None:
            return False

        current = self._get_data_fingerprint()
        cached = self._cached_context.data_fingerprint

        return (
            current.last_sync_timestamp == cached.last_sync_timestamp
            and current.analysis_file_mtimes == cached.analysis_file_mtimes
            and current.hevy_workout_count == cached.hevy_workout_count
            and current.local_date == cached.local_date
        )

    def _build_context_cache(self) -> CachedChatContext:
        """Build and cache the system message with reference data.

        Reference data (recent analyses, Garmin activities, HEVY workouts) is
        folded into the system message as labelled sections rather than
        injected as fabricated user/assistant turns.

        Returns:
            CachedChatContext with the composed system message and token count
        """
        system_message = self._build_system_message()

        context_sections: list[str] = []

        analyses = self.get_historical_analyses(days=self.ANALYSES_CONTEXT_DAYS)
        analyses_context = self._format_analyses_context(analyses) if analyses else None
        if analyses_context:
            context_sections.append(analyses_context)

        activities_context = self._get_recent_activities_context(days=7)
        if activities_context:
            context_sections.append(activities_context)

        hevy_context = self._get_recent_hevy_context(days=7)
        if hevy_context:
            context_sections.append(hevy_context)

        if context_sections:
            system_message += (
                "\n\n# Reference Data\n"
                "Current data from the user's local database (tools can fetch "
                "more or older data on demand):\n\n"
                + "\n\n".join(context_sections)
            )

        return CachedChatContext(
            system_message=system_message,
            cache_timestamp=datetime.now(timezone.utc),
            data_fingerprint=self._get_data_fingerprint(),
            token_count=len(system_message) // 4,
        )

    def build_context_messages(self) -> list[dict]:
        """Build the message list: cached system message, dated history, "now" note.

        Stored messages are replayed verbatim. Time reaches the model only
        through developer notes: a header at the start of each session, and
        one note, built fresh per request and never stored, just before the
        latest user message.

        Returns:
            List of message dicts ready for OpenAI API
        """
        # Ensure cache is valid
        if not self._is_cache_valid():
            self._cached_context = self._build_context_cache()

        cache = self._cached_context
        messages: list[dict] = [{"role": "system", "content": cache.system_message}]
        token_count = cache.token_count

        # Chat history (always fresh - it grows each message).
        # Walk newest-first so that when history exceeds the budget we drop the
        # OLDEST turns and keep the most recent ones (including the question the
        # user just asked), then restore chronological order for the model.
        chat_messages = self.repo.get_chat_history(limit=self.CHAT_HISTORY_LIMIT)
        kept = []
        for msg in reversed(chat_messages):
            msg_tokens = msg.token_estimate or len(msg.content) // 4
            if token_count + msg_tokens > self.CONTEXT_BUDGET:
                break  # Older messages beyond budget are dropped
            kept.append(msg)
            token_count += msg_tokens
        kept.reverse()

        messages.extend(self._render_history(kept))
        return messages

    def _render_history(self, history: list) -> list[dict]:
        """Interleave session headers into the history and add the "now" note.

        Headers carry absolute times only, so the replayed prefix stays
        byte-identical between requests (prompt caching keeps working). Every
        relative phrase lives in the per-request note at the end.
        """
        rendered: list[dict] = []
        session_starts: list[datetime] = []
        previous: datetime | None = None
        for msg in history:
            # created_at comes from SQLite CURRENT_TIMESTAMP, i.e. naive UTC
            sent = temporal.from_utc_naive(getattr(msg, "created_at", None), self.config.timezone)
            if sent is not None:
                new_session = (
                    previous is None
                    or sent - previous > self.SESSION_GAP
                    or sent.date() != previous.date()
                )
                if new_session:
                    session_starts.append(sent)
                    rendered.append({
                        "role": "developer",
                        "content": f"Session started {temporal.timestamp_label(sent)}.",
                    })
                previous = sent
            rendered.append({"role": msg.role, "content": msg.content})

        now_note = {"role": "developer", "content": self._build_now_note(session_starts)}
        last_user = next(
            (i for i in range(len(rendered) - 1, -1, -1) if rendered[i]["role"] == "user"),
            None,
        )
        if last_user is None:
            rendered.append(now_note)
        else:
            rendered.insert(last_user, now_note)
        return rendered

    def _build_now_note(self, session_starts: list[datetime]) -> str:
        """Current time, how long ago earlier sessions were, and data freshness."""
        now = self._now()
        lines = [f"Current time: {temporal.timestamp_label(now)}."]

        # The last session is the one holding the question being answered.
        earlier_days: list[str] = []
        for start in session_starts[:-1]:
            label = temporal.day_label(start.date(), now.date())
            if label not in earlier_days:
                earlier_days.append(label)
        if earlier_days:
            lines.append(
                f"Earlier sessions in this conversation: {', '.join(earlier_days)}. "
                'Words like "today" or "tomorrow" inside a session refer to that '
                "session's own date, not to now."
            )

        lines.append(self._get_data_freshness_info(now))
        return "\n".join(lines)

    def _get_today_activities_summary(self) -> str:
        """Get a summary of activities completed today in the configured timezone.

        Uses start_time_local column to correctly identify activities
        that occurred today in the user's local timezone, avoiding
        UTC/local date mismatches.

        Returns:
            String summary or "none"
        """
        activities = self.repo.get_activities_by_local_date(self._today().isoformat())

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
                miles = meters_to_miles(act.distance_meters)
                parts.append(f"({miles:.1f} mi)")

            if act.duration_seconds:
                mins = int(act.duration_seconds / 60)
                parts.append(f"{mins} min")

            summaries.append(" ".join(parts))

        return "; ".join(summaries)

    def _build_system_message(self) -> str:
        """Build the system message with coach persona and context.

        Deliberately clock-free: the current time and data freshness go in a
        per-request developer note (see ``_build_now_note``), so this cached
        message never goes stale mid-session.
        """
        # Use tools-aware system message when tools are enabled
        base_message = COACH_SYSTEM_MESSAGE_WITH_TOOLS if self._use_tools else COACH_SYSTEM_MESSAGE
        parts = [base_message]
        today = self._today()

        # Get today's activities for template substitution
        completed_today = self._get_today_activities_summary()

        # Process templates in schedule and user_context
        processed_schedule = process_template(
            self.config.schedule,
            timezone=self.config.timezone,
            completed_today=completed_today,
        )
        processed_context = process_template(
            self.config.user_context,
            timezone=self.config.timezone,
            completed_today=completed_today,
        )

        if processed_schedule.strip():
            week = temporal.map_schedule_to_dates(processed_schedule, today)
            if week:
                lines = "\n".join(
                    f"- {temporal.day_label(day, today)}: {session}" for day, session in week
                )
                parts.append(f"\n\nUser's training schedule this week:\n{lines}")
            else:
                parts.append(
                    f"\n\nUser's typical training schedule:\n{processed_schedule}"
                )

        if processed_context.strip():
            parts.append(
                f"\n\nAdditional context about the user:\n{processed_context}"
            )

        parts.append(
            "\n\nTime context: the replayed conversation includes a developer "
            "note at the start of each session giving its date and time, and a "
            "note with the current time comes right before the user's latest "
            "message. Use those notes to place earlier messages in time; never "
            "assume an earlier session happened today."
        )

        parts.append(
            "\n\nYou have access to the user's historical fitness analyses. "
            "Reference specific data points when giving advice. "
            "Keep responses concise but actionable."
        )

        return "".join(parts)

    def _get_data_freshness_info(self, now: datetime | None = None) -> str:
        """Describe when data was last synced, relative to now.

        ``sync_metadata`` stores naive local wall-clock timestamps.
        """
        now = now or self._now()
        last_sync = temporal.from_local_naive(
            self.repo.get_latest_sync_timestamp(), self.config.timezone
        )
        if last_sync is None:
            return "⚠️ Data freshness: no successful sync found. Data may be stale."

        relative = temporal.relative_day(last_sync.date(), now.date())
        day = relative if relative in ("today", "yesterday") else temporal.short_date(last_sync.date())
        line = (
            f"Data last synced {day} at {temporal.clock_time(last_sync)} "
            f"({temporal.age_phrase(last_sync, now)})."
        )
        if now - last_sync > timedelta(hours=24):
            return (
                f"⚠️ {line} Data may be stale; recommend the user runs "
                "'garmin-sync sync all' before giving detailed advice."
            )
        return line

    def _format_analyses_context(self, analyses: list[dict]) -> str | None:
        """Format recent daily analyses as a context section.

        Today's report is included in full. Earlier reports contribute only
        their decisions (the daily call and the plan, every day resolved to a
        date): numbers quoted in them may have been revised since, and
        replaying their prose made the coach repeat stale readings.

        Args:
            analyses: List of analysis dicts with 'date' and 'content'

        Returns:
            Formatted string for context, or None if nothing usable remains
        """
        today = self._today()
        header = [
            "## Recent Daily Analyses",
            "Numbers quoted in an analysis reflect the data when it was written and may "
            "have been revised since; check current values with tools before relying on them.",
        ]
        parts: list[str] = []

        for analysis in analyses:
            written = date.fromisoformat(analysis["date"])
            label = temporal.day_label(written, today)
            if written == today:
                # Truncate long analyses to save tokens
                content = analysis["content"]
                if len(content) > 3000:
                    content = content[:3000] + "\n...[truncated]"
                parts.append(f"\n### Analysis written {label}\n{content}")
            else:
                decisions = summarize_decisions(analysis["content"], written, today)
                if decisions:
                    parts.append(f"\n### Decisions from the analysis written {label}\n{decisions}")

        return "\n".join(header + parts) if parts else None

    def _get_recent_activities_context(self, days: int = 7) -> str | None:
        """Get recent Garmin activities for chat context.

        This fetches fresh data directly from the database, ensuring the AI
        can see recent activities even if they were synced after the last analysis.

        Args:
            days: Number of days to look back

        Returns:
            Formatted string with activity details, or None if no data
        """
        today = self._today()
        start_date = (today - timedelta(days=days)).isoformat()
        activities = self.repo.get_activities(start_date=start_date, limit=50)

        if not activities:
            return None

        parts = ["## Recent Garmin Activities (Last 7 Days)\n"]

        for act in activities:
            # Local start time (not UTC), labelled relative to today
            started = temporal.parse_iso(act.start_time_local or act.start_time)
            when = (
                f"{temporal.day_label(started.date(), today)} @ {temporal.clock_time(started)}"
                if started
                else "N/A"
            )
            name = act.activity_name or act.activity_type or "Activity"

            # Format duration
            duration_mins = round(act.duration_seconds / 60) if act.duration_seconds else None
            duration_str = f"{duration_mins} min" if duration_mins else ""

            # Format distance and pace
            distance_str = ""
            pace_str = ""
            if act.distance_meters and act.distance_meters > 0:
                distance_miles = meters_to_miles(act.distance_meters)
                if distance_miles >= 1:
                    distance_str = f"{distance_miles:.1f} mi"
                else:
                    distance_str = f"{distance_miles:.2f} mi"

                # Calculate pace for running/walking activities
                if act.duration_seconds and act.activity_type in (
                    "running", "treadmill_running", "trail_running", "walking", "hiking"
                ):
                    sec_mi = pace_sec_per_mile(act.duration_seconds, act.distance_meters)
                    pace_str = f"pace {int(sec_mi // 60)}:{int(sec_mi % 60):02d}/mi"

            # Max speed → best instantaneous pace for run types
            best_str = ""
            if act.max_speed_mps and act.max_speed_mps > 0:
                if act.activity_type in (
                    "running", "treadmill_running", "trail_running"
                ):
                    best_sec_mi = pace_sec_per_mile(1, act.max_speed_mps)
                    best_str = (
                        f"max {int(best_sec_mi // 60)}:"
                        f"{int(best_sec_mi % 60):02d}/mi"
                    )
                else:
                    best_str = f"max {mps_to_mph(act.max_speed_mps):.1f} mph"

            # Format heart rate (avg and max)
            hr_str = ""
            if act.average_hr and act.max_hr:
                hr_str = f"HR {int(act.average_hr)}/{int(act.max_hr)}"
            elif act.average_hr:
                hr_str = f"avg HR {int(act.average_hr)}"

            # Format training effects
            te_str = ""
            if act.training_effect_aerobic or act.training_effect_anaerobic:
                aerobic = f"{act.training_effect_aerobic:.1f}" if act.training_effect_aerobic else "-"
                anaerobic = f"{act.training_effect_anaerobic:.1f}" if act.training_effect_anaerobic else "-"
                te_str = f"TE {aerobic}/{anaerobic}"

            # Format training load
            load_str = f"load {act.training_load:.0f}" if act.training_load else ""

            # Format HR drift (aerobic decoupling)
            drift_str = ""
            if act.hr_drift is not None:
                drift_pct = act.hr_drift * 100
                drift_str = f"drift {drift_pct:+.1f}%"

            # Format elevation
            elev_str = ""
            if act.elevation_gain_meters and act.elevation_gain_meters > 10:
                elev_str = f"elev +{int(meters_to_feet(act.elevation_gain_meters))}ft"

            # Format cadence (for running)
            cadence_str = ""
            if act.avg_cadence and act.activity_type in (
                "running", "treadmill_running", "trail_running"
            ):
                cadence_str = f"cadence {int(act.avg_cadence)} spm"

            # Format calories
            cal_str = f"{act.calories} cal" if act.calories else ""

            # Build details string - primary metrics first
            primary = ", ".join(filter(None, [duration_str, distance_str, pace_str, best_str, hr_str]))
            secondary = ", ".join(filter(None, [te_str, load_str, drift_str, elev_str, cadence_str, cal_str]))

            if secondary:
                parts.append(f"- **{when}**: {name} ({primary})")
                parts.append(f"  [{secondary}]")
            else:
                parts.append(f"- **{when}**: {name} ({primary})")

        return "\n".join(parts)

    def _get_recent_hevy_context(self, days: int = 7) -> str | None:
        """Get recent HEVY workout details for chat context.

        This fetches fresh data directly from the database, ensuring the AI
        can see recent workouts even if they were synced after the last analysis.

        Args:
            days: Number of days to look back

        Returns:
            Formatted string with workout details, or None if no data
        """
        workouts = self.repo.get_hevy_workout_details(days=days)

        if not workouts:
            return None

        today = self._today()
        parts = ["## Recent Strength Training (Last 7 Days)\n"]

        for w in workouts:
            when = w.get("date") or "N/A"
            try:
                when = temporal.day_label(date.fromisoformat(when), today)
            except ValueError:
                pass
            time_str = w.get("time")
            if time_str:
                try:
                    time_str = temporal.clock_time(datetime.strptime(time_str, "%H:%M"))
                except ValueError:
                    pass
            time_display = f" @ {time_str}" if time_str else ""
            title = safe_user_string(w.get("title", "Workout"))
            volume = w.get("total_volume_lbs", 0)
            duration = w.get("duration_minutes")
            duration_str = f", {duration} min" if duration else ""

            parts.append(
                f"\n### {when}{time_display}: <hevy_title>{title}</hevy_title> "
                f"({volume:,} lbs{duration_str})"
            )

            exercises = w.get("exercises", [])
            for ex in exercises:
                name = safe_user_string(ex.get("name", "Unknown"))
                muscle = safe_user_string(ex.get("muscle_group", ""))
                sets = ex.get("sets", "")
                muscle_str = f" ({muscle})" if muscle else ""
                parts.append(f"- <hevy_exercise>{name}</hevy_exercise>{muscle_str}: {sets}")

        return "\n".join(parts)

    def send_message(self, user_input: str) -> str:
        """Send a message and get a response.

        Args:
            user_input: The user's message

        Returns:
            The assistant's response

        Raises:
            OpenAIAnalysisError: If the API call fails
        """
        # Save user message to database
        self.repo.add_chat_message(
            role="user",
            content=user_input,
            message_type="chat",
        )

        # Build context with history
        messages = self.build_context_messages()

        # Call OpenAI - with or without tool calling
        if self._use_tools:
            response = chat_with_tools(
                messages=messages,
                tools=TOOLS,
                api_key=self.config.api_key,
                model=None,  # Use default tool model (gpt-5.4)
                tool_executor=self.tool_executor,
            )
        else:
            response = chat_with_history(
                messages=messages,
                api_key=self.config.api_key,
                model=self.config.model,
            )

        # Save assistant response to database
        self.repo.add_chat_message(
            role="assistant",
            content=response,
            message_type="chat",
        )

        return response

    def get_context_summary(self) -> dict:
        """Get a summary of the current context.

        Returns:
            Dict with context statistics including cache status
        """
        analyses = self.get_historical_analyses(days=self.ANALYSES_CONTEXT_DAYS)
        chat_messages = self.repo.get_chat_history(limit=self.CHAT_HISTORY_LIMIT)
        token_total = self.repo.get_chat_token_total()
        hevy_workouts = self.repo.get_hevy_workout_details(days=7)

        # Get Garmin activity count
        start_date = (self._today() - timedelta(days=7)).isoformat()
        garmin_activities = self.repo.get_activities(start_date=start_date, limit=50)

        # Calculate cache age if cache exists
        cache_age_seconds: float | None = None
        if self._cached_context is not None:
            age = datetime.now(timezone.utc) - self._cached_context.cache_timestamp
            cache_age_seconds = age.total_seconds()

        return {
            "analysis_count": len(analyses),
            "analysis_dates": [a["date"] for a in analyses],
            "garmin_activity_count": len(garmin_activities),
            "hevy_workout_count": len(hevy_workouts),
            "chat_message_count": len(chat_messages),
            "estimated_tokens": token_total,
            "token_budget": self.CONTEXT_BUDGET,
            "cache_age_seconds": cache_age_seconds,
            "tools_enabled": self._use_tools,
            "tool_count": len(TOOLS) if self._use_tools else 0,
        }

    def clear_history(self) -> int:
        """Clear chat history and invalidate cache.

        Returns:
            Number of messages deleted
        """
        count = self.repo.clear_chat_history()
        self._cached_context = None  # Force rebuild on next message
        return count
