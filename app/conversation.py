"""Application-owned state for one interactive feedback conversation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def _normalise_text(value: str) -> str:
    """Normalise spacing and case for safe user-message grounding checks."""

    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class UserMessage:
    """One user-authored message and the time at which it reached the app."""

    text: str
    received_at: datetime


@dataclass
class ConversationSession:
    """State that belongs to one user conversation, not to the agent instance."""

    conversation_id: str
    user_messages: list[UserMessage] = field(default_factory=list)
    closed: bool = False

    def add_user_message(self, text: str, received_at: datetime) -> None:
        self.user_messages.append(UserMessage(text=text, received_at=received_at))

    def matching_user_message(self, text: str) -> UserMessage | None:
        """Return the most recent user message containing the supplied text."""

        normalised_text = _normalise_text(text)
        if not normalised_text:
            return None

        for message in reversed(self.user_messages):
            if normalised_text in _normalise_text(message.text):
                return message

        return None
