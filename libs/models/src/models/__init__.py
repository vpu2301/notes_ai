"""Model hosting is configuration: ``Registry.load(...)`` → ``resolve(workspace, operation)`` → ``build_*_provider``."""

from __future__ import annotations

from .asr_http import HTTPASRProvider
from .asr_inproc import InProcASRProvider, InProcEngine
from .config import (
    BackendConfig,
    LoadedConfig,
    ModelsConfig,
    ProcessorInfo,
    load_config,
    parse_config,
)
from .errors import (
    PROVIDER_RETRY_KINDS,
    RETRYABLE_KINDS,
    ConfigError,
    ErrorKind,
    ProviderError,
    TranscriptionCancelledError,
)
from .factory import build_asr_provider, build_chat_provider
from .openai_compat import OpenAICompatibleChatProvider
from .protocols import (
    ASRProvider,
    ChatProvider,
    EmbeddingProvider,
    JsonSchema,
    ProviderResult,
    ShouldCancel,
    SpeechRun,
)
from .recorded import RecordedChatProvider
from .registry import (
    ActiveOverride,
    Capabilities,
    Registry,
    ResolvedBackend,
    WorkspaceModelSettings,
)
from .usage import UsageRecord, UsageSink, emit, set_usage_sink

__all__ = [
    "ASRProvider",
    "ActiveOverride",
    "BackendConfig",
    "Capabilities",
    "ChatProvider",
    "ConfigError",
    "EmbeddingProvider",
    "ErrorKind",
    "HTTPASRProvider",
    "InProcASRProvider",
    "InProcEngine",
    "JsonSchema",
    "LoadedConfig",
    "ModelsConfig",
    "OpenAICompatibleChatProvider",
    "PROVIDER_RETRY_KINDS",
    "ProcessorInfo",
    "ProviderError",
    "ProviderResult",
    "RETRYABLE_KINDS",
    "RecordedChatProvider",
    "Registry",
    "ResolvedBackend",
    "ShouldCancel",
    "SpeechRun",
    "TranscriptionCancelledError",
    "UsageRecord",
    "UsageSink",
    "WorkspaceModelSettings",
    "build_asr_provider",
    "build_chat_provider",
    "emit",
    "load_config",
    "parse_config",
    "set_usage_sink",
]
