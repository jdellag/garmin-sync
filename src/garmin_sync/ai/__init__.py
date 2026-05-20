"""AI-powered fitness analysis module."""

from garmin_sync.ai.chat import ChatSession
from garmin_sync.ai.config import AIConfig, load_config, save_config
from garmin_sync.ai.openai_client import (
    COACH_SYSTEM_MESSAGE,
    OpenAIAnalysisError,
    analyze_fitness_data,
    chat_with_history,
)
from garmin_sync.ai.prompt_builder import (
    LONGITUDINAL_SYSTEM_MESSAGE,
    build_analysis_prompt,
    build_longitudinal_prompt,
    generate_baseline_summary,
    generate_detailed_7d,
    process_template,
)

__all__ = [
    "AIConfig",
    "ChatSession",
    "COACH_SYSTEM_MESSAGE",
    "LONGITUDINAL_SYSTEM_MESSAGE",
    "load_config",
    "save_config",
    "analyze_fitness_data",
    "chat_with_history",
    "OpenAIAnalysisError",
    "build_analysis_prompt",
    "build_longitudinal_prompt",
    "generate_baseline_summary",
    "generate_detailed_7d",
    "process_template",
]
