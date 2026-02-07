"""Notification service (Phase 3I).

Dispatches notifications to configured channels (Telegram, Webhook, Push).
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Protocol
from uuid import UUID

import httpx

from loop_symphony.models.notification import (
    ChannelConfig,
    Notification,
    NotificationChannel,
    NotificationHistory,
    NotificationPreferences,
    NotificationPriority,
    NotificationResult,
    NotificationType,
)

logger = logging.getLogger(__name__)


# Default timeout for HTTP requests
DEFAULT_TIMEOUT = 10.0


class PreferencesStore(Protocol):
    """Protocol for fetching notification preferences."""

    async def get_preferences(
        self,
        user_id: UUID,
        app_id: UUID,
    ) -> NotificationPreferences | None:
        """Get notification preferences for a user."""
        ...


class ChannelNotifier(ABC):
    """Base class for channel-specific notifiers."""

    @property
    @abstractmethod
    def channel(self) -> NotificationChannel:
        """The channel this notifier handles."""
        ...

    @abstractmethod
    async def send(
        self,
        notification: Notification,
        config: ChannelConfig,
    ) -> NotificationResult:
        """Send a notification via this channel."""
        ...

    def _make_result(
        self,
        notification: Notification,
        success: bool,
        error_message: str | None = None,
        external_id: str | None = None,
    ) -> NotificationResult:
        """Create a NotificationResult."""
        return NotificationResult(
            notification_id=notification.id,
            channel=self.channel,
            success=success,
            error_message=error_message,
            external_id=external_id,
        )


class TelegramNotifier(ChannelNotifier):
    """Send notifications via Telegram Bot API."""

    def __init__(self, bot_token: str | None = None) -> None:
        """Initialize with Telegram bot token.

        Args:
            bot_token: Telegram Bot API token. If None, sending will fail.
        """
        self._bot_token = bot_token
        self._base_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.TELEGRAM

    async def send(
        self,
        notification: Notification,
        config: ChannelConfig,
    ) -> NotificationResult:
        """Send notification via Telegram."""
        if not self._bot_token:
            return self._make_result(
                notification,
                success=False,
                error_message="Telegram bot token not configured",
            )

        if not config.telegram_chat_id:
            return self._make_result(
                notification,
                success=False,
                error_message="Telegram chat_id not configured for user",
            )

        # Format message
        text = self._format_message(notification)

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.post(
                    f"{self._base_url}/sendMessage",
                    json={
                        "chat_id": config.telegram_chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    message_id = data.get("result", {}).get("message_id")
                    return self._make_result(
                        notification,
                        success=True,
                        external_id=str(message_id) if message_id else None,
                    )
                else:
                    return self._make_result(
                        notification,
                        success=False,
                        error_message=f"Telegram API error: {response.status_code}",
                    )

        except httpx.TimeoutException:
            return self._make_result(
                notification,
                success=False,
                error_message="Telegram request timed out",
            )
        except Exception as e:
            logger.exception("Telegram notification failed")
            return self._make_result(
                notification,
                success=False,
                error_message=str(e),
            )

    def _format_message(self, notification: Notification) -> str:
        """Format notification for Telegram."""
        emoji = self._get_emoji(notification.type, notification.priority)
        return f"{emoji} <b>{notification.title}</b>\n\n{notification.body}"

    def _get_emoji(
        self,
        type: NotificationType,
        priority: NotificationPriority,
    ) -> str:
        """Get emoji for notification type."""
        if priority == NotificationPriority.CRITICAL:
            return "\u26a0\ufe0f"  # Warning sign

        type_emojis = {
            NotificationType.TASK_COMPLETE: "\u2705",  # Check mark
            NotificationType.TASK_FAILED: "\u274c",    # X mark
            NotificationType.HEARTBEAT_RESULT: "\U0001f4ac",  # Speech bubble
            NotificationType.SYSTEM_ALERT: "\U0001f514",  # Bell
            NotificationType.TRUST_ESCALATION: "\u2b50",  # Star
        }
        return type_emojis.get(type, "\U0001f4e8")  # Default: envelope


class WebhookNotifier(ChannelNotifier):
    """Send notifications via HTTP webhook."""

    def __init__(self, default_headers: dict[str, str] | None = None) -> None:
        """Initialize with optional default headers."""
        self._default_headers = default_headers or {}

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.WEBHOOK

    async def send(
        self,
        notification: Notification,
        config: ChannelConfig,
    ) -> NotificationResult:
        """Send notification via webhook."""
        if not config.webhook_url:
            return self._make_result(
                notification,
                success=False,
                error_message="Webhook URL not configured",
            )

        payload = {
            "id": str(notification.id),
            "type": notification.type.value,
            "title": notification.title,
            "body": notification.body,
            "priority": notification.priority.value,
            "task_id": notification.task_id,
            "data": notification.data,
            "timestamp": notification.created_at.isoformat(),
        }

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.post(
                    config.webhook_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        **self._default_headers,
                    },
                )

                if 200 <= response.status_code < 300:
                    return self._make_result(
                        notification,
                        success=True,
                    )
                else:
                    return self._make_result(
                        notification,
                        success=False,
                        error_message=f"Webhook returned {response.status_code}",
                    )

        except httpx.TimeoutException:
            return self._make_result(
                notification,
                success=False,
                error_message="Webhook request timed out",
            )
        except Exception as e:
            logger.exception("Webhook notification failed")
            return self._make_result(
                notification,
                success=False,
                error_message=str(e),
            )


class PushNotifier(ChannelNotifier):
    """Send push notifications (placeholder for APNs integration)."""

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.PUSH

    async def send(
        self,
        notification: Notification,
        config: ChannelConfig,
    ) -> NotificationResult:
        """Send push notification.

        Note: Actual APNs integration would require:
        - Apple Developer account
        - APNs certificates or keys
        - pyapns2 or similar library

        For now, this is a placeholder that logs the intent.
        """
        if not config.push_device_token:
            return self._make_result(
                notification,
                success=False,
                error_message="Push device token not configured",
            )

        # Log for debugging - actual implementation would send to APNs
        logger.info(
            f"Push notification (not sent - placeholder): "
            f"token={config.push_device_token[:20]}..., "
            f"title={notification.title}"
        )

        # Return success=False since we're not actually sending
        return self._make_result(
            notification,
            success=False,
            error_message="Push notifications not implemented (placeholder)",
        )


class Notifier:
    """Main notification dispatcher.

    Coordinates sending notifications across multiple channels based on
    user preferences and notification priority.
    """

    def __init__(
        self,
        preferences_store: PreferencesStore | None = None,
        telegram_bot_token: str | None = None,
    ) -> None:
        """Initialize the notifier.

        Args:
            preferences_store: Store for fetching user preferences
            telegram_bot_token: Token for Telegram Bot API
        """
        self._preferences_store = preferences_store
        self._history: list[NotificationHistory] = []

        # Initialize channel notifiers
        self._notifiers: dict[NotificationChannel, ChannelNotifier] = {
            NotificationChannel.TELEGRAM: TelegramNotifier(telegram_bot_token),
            NotificationChannel.WEBHOOK: WebhookNotifier(),
            NotificationChannel.PUSH: PushNotifier(),
        }

    async def send(
        self,
        notification: Notification,
        preferences: NotificationPreferences | None = None,
    ) -> NotificationHistory:
        """Send a notification to a user.

        Args:
            notification: The notification to send
            preferences: User preferences (fetched if not provided)

        Returns:
            NotificationHistory with results from each channel
        """
        # Get preferences if not provided
        if preferences is None and notification.user_id and notification.app_id:
            if self._preferences_store:
                preferences = await self._preferences_store.get_preferences(
                    notification.user_id,
                    notification.app_id,
                )

        # Determine which channels to use
        channels_to_use = self._select_channels(notification, preferences)

        # Send to each channel
        results: list[NotificationResult] = []
        for channel in channels_to_use:
            config = self._get_channel_config(channel, preferences)
            if config and config.enabled:
                notifier = self._notifiers.get(channel)
                if notifier:
                    result = await notifier.send(notification, config)
                    results.append(result)

        # Create history record
        history = NotificationHistory(
            notification_id=notification.id,
            user_id=notification.user_id,
            app_id=notification.app_id,
            type=notification.type,
            title=notification.title,
            body=notification.body,
            results=results,
        )

        self._history.append(history)
        return history

    def _select_channels(
        self,
        notification: Notification,
        preferences: NotificationPreferences | None,
    ) -> list[NotificationChannel]:
        """Select which channels to use for a notification."""
        # If notification specifies channels, use those
        if notification.channels:
            return notification.channels

        # If no preferences, default to webhook only
        if not preferences or not preferences.enabled:
            return []

        # Check notification type preferences
        if notification.type == NotificationType.TASK_COMPLETE:
            if not preferences.notify_on_complete:
                return []
        elif notification.type == NotificationType.TASK_FAILED:
            if not preferences.notify_on_failure:
                return []
        elif notification.type == NotificationType.HEARTBEAT_RESULT:
            if not preferences.notify_on_heartbeat:
                return []

        # Return all enabled channels that meet priority threshold
        channels = []
        for config in preferences.channels:
            if config.enabled:
                if notification.priority.value >= config.min_priority.value:
                    channels.append(config.channel)

        return channels

    def _get_channel_config(
        self,
        channel: NotificationChannel,
        preferences: NotificationPreferences | None,
    ) -> ChannelConfig | None:
        """Get configuration for a specific channel."""
        if not preferences:
            return None

        for config in preferences.channels:
            if config.channel == channel:
                return config

        return None

    async def send_task_complete(
        self,
        user_id: UUID,
        app_id: UUID,
        task_id: str,
        summary: str,
        confidence: float,
    ) -> NotificationHistory:
        """Convenience method for task completion notifications."""
        notification = Notification(
            user_id=user_id,
            app_id=app_id,
            type=NotificationType.TASK_COMPLETE,
            title="Task Complete",
            body=summary,
            priority=NotificationPriority.NORMAL,
            task_id=task_id,
            data={"confidence": confidence},
        )
        return await self.send(notification)

    async def send_task_failed(
        self,
        user_id: UUID,
        app_id: UUID,
        task_id: str,
        error_message: str,
    ) -> NotificationHistory:
        """Convenience method for task failure notifications."""
        notification = Notification(
            user_id=user_id,
            app_id=app_id,
            type=NotificationType.TASK_FAILED,
            title="Task Failed",
            body=error_message,
            priority=NotificationPriority.HIGH,
            task_id=task_id,
        )
        return await self.send(notification)

    async def send_system_alert(
        self,
        title: str,
        body: str,
        priority: NotificationPriority = NotificationPriority.HIGH,
        channels: list[NotificationChannel] | None = None,
    ) -> NotificationHistory:
        """Send a system-wide alert (not user-specific)."""
        notification = Notification(
            type=NotificationType.SYSTEM_ALERT,
            title=title,
            body=body,
            priority=priority,
            channels=channels or [NotificationChannel.WEBHOOK],
        )
        return await self.send(notification)

    def get_history(
        self,
        user_id: UUID | None = None,
        limit: int = 50,
    ) -> list[NotificationHistory]:
        """Get notification history, optionally filtered by user."""
        history = self._history
        if user_id:
            history = [h for h in history if h.user_id == user_id]

        # Sort by created_at descending
        sorted_history = sorted(
            history,
            key=lambda h: h.created_at,
            reverse=True,
        )
        return sorted_history[:limit]

    def register_notifier(
        self,
        channel: NotificationChannel,
        notifier: ChannelNotifier,
    ) -> None:
        """Register a custom channel notifier."""
        self._notifiers[channel] = notifier
