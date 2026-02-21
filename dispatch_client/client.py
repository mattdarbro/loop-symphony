"""Dispatch client — stub for future Dispatch app integration."""

import logging
from uuid import UUID

from dispatch_client.models import (
    ChannelType,
    DispatchChannel,
    DispatchMessage,
    MessagePriority,
)

logger = logging.getLogger(__name__)


class DispatchClient:
    """Client for communicating with the Dispatch system.

    This is a stub implementation. The real Dispatch app will
    provide the backend that fulfills this contract.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url
        self._channels: dict[str, DispatchChannel] = {}
        self._outbox: list[DispatchMessage] = []

    async def send(self, message: DispatchMessage) -> bool:
        """Send a message through Dispatch.

        Returns True if queued successfully (stub always returns True).
        """
        self._outbox.append(message)
        logger.debug(f"Dispatch stub: queued message {message.id} to {message.channel}")
        return True

    async def receive(self, channel: str, since: UUID | None = None) -> list[DispatchMessage]:
        """Receive messages from a channel.

        Stub returns empty list.
        """
        logger.debug(f"Dispatch stub: receive from {channel}")
        return []

    async def create_channel(
        self,
        name: str,
        channel_type: ChannelType = ChannelType.DIRECT,
        participants: list[str] | None = None,
    ) -> DispatchChannel:
        """Create or get a communication channel."""
        if name in self._channels:
            return self._channels[name]
        channel = DispatchChannel(
            name=name,
            channel_type=channel_type,
            participants=participants or [],
        )
        self._channels[name] = channel
        logger.debug(f"Dispatch stub: created channel {name}")
        return channel

    async def list_channels(self) -> list[DispatchChannel]:
        """List all known channels."""
        return list(self._channels.values())

    @property
    def pending_count(self) -> int:
        """Number of messages in the outbox."""
        return len(self._outbox)

    def flush_outbox(self) -> list[DispatchMessage]:
        """Return and clear all queued messages."""
        messages = list(self._outbox)
        self._outbox.clear()
        return messages
