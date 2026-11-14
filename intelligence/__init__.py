"""Classification and speech adapters for the local pager."""

from pathlib import Path
from typing import Protocol

from contracts import ClassificationResult, NotificationInput, Settings

from .classifier import DemoClassifier, OpenAIClassifier
from .common import ProviderError
from .group_summary import GroupSummarizer, build_group_summarizer
from .speech import MacOSSpeech, OpenAISpeech, validate_wav

__all__ = [
    "Classifier",
    "GroupSummarizer",
    "ProviderError",
    "SpeechProvider",
    "build_group_summarizer",
    "build_providers",
    "validate_wav",
]


class Classifier(Protocol):
    async def classify(self, notification: NotificationInput) -> ClassificationResult: ...

    async def classify_batch(
        self, notifications: list[NotificationInput]
    ) -> list[ClassificationResult]: ...


class SpeechProvider(Protocol):
    async def synthesize(self, text: str, destination: Path) -> Path: ...


def build_providers(settings: Settings) -> tuple[Classifier, SpeechProvider]:
    classifier = (
        DemoClassifier() if settings.classifier_provider == "demo" else OpenAIClassifier(settings)
    )
    speech = MacOSSpeech(settings) if settings.tts_provider == "macos" else OpenAISpeech(settings)
    return classifier, speech
