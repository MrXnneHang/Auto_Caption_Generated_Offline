from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, TypedDict, Union

from pydantic import BaseModel

if TYPE_CHECKING:
    from lab.agent.output_types import Actions, DisplayText

# Type definitions
WebSocketSend = Callable[[str], Awaitable[None]]
BroadcastFunc = Callable[[list[str], dict, str | None], Awaitable[None]]


class AudioPayload(TypedDict):
    """Type definition for audio payload"""

    type: str
    audio: str | None
    volumes: list[float] | None
    slice_length: int | None
    display_text: DisplayText | None
    actions: Actions | None
    forwarded: bool | None
    turn_id: str | None


@dataclass
class BroadcastContext:
    """Context for broadcasting messages in group chat"""

    broadcast_func: BroadcastFunc | None = None
    group_members: list[str] | None = None
    current_client_uid: str | None = None


class ConversationConfig(BaseModel):
    """Configuration for conversation chain"""

    conf_uid: str = ""
    history_uid: str = ""
    client_uid: str = ""
    character_name: str = "AI"


@dataclass
class GroupConversationState:
    """State for group conversation"""

    # Class variable to track current states
    _states: ClassVar[dict[str, "GroupConversationState"]] = {}  # noqa: UP037

    group_id: str
    conversation_history: list[str] = field(default_factory=list[str])
    memory_index: dict[str, int] = field(default_factory=dict[str, int])
    group_queue: list[str] = field(default_factory=list[str])
    session_emoji: str = ""
    current_speaker_uid: str | None = None

    def __post_init__(self):
        """Register state instance after initialization"""
        GroupConversationState._states[self.group_id] = self

    @classmethod
    def get_state(cls, group_id: str) -> Union["GroupConversationState", None]:  # noqa: UP037 UP007
        """Get conversation state by group_id"""
        return cls._states.get(group_id)

    @classmethod
    def remove_state(cls, group_id: str) -> None:
        """Remove conversation state when done"""
        cls._states.pop(group_id, None)
