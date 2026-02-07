"""Tests for notification layer (Phase 3I)."""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

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
from loop_symphony.services.notifier import (
    Notifier,
    TelegramNotifier,
    WebhookNotifier,
    PushNotifier,
)


class TestNotificationChannel:
    """Tests for NotificationChannel enum."""

    def test_channels(self):
        assert NotificationChannel.TELEGRAM.value == "telegram"
        assert NotificationChannel.WEBHOOK.value == "webhook"
        assert NotificationChannel.PUSH.value == "push"
        assert NotificationChannel.EMAIL.value == "email"


class TestNotificationPriority:
    """Tests for NotificationPriority enum."""

    def test_priorities(self):
        assert NotificationPriority.LOW.value == "low"
        assert NotificationPriority.NORMAL.value == "normal"
        assert NotificationPriority.HIGH.value == "high"
        assert NotificationPriority.CRITICAL.value == "critical"


class TestNotificationType:
    """Tests for NotificationType enum."""

    def test_types(self):
        assert NotificationType.TASK_COMPLETE.value == "task_complete"
        assert NotificationType.TASK_FAILED.value == "task_failed"
        assert NotificationType.HEARTBEAT_RESULT.value == "heartbeat_result"
        assert NotificationType.SYSTEM_ALERT.value == "system_alert"


class TestChannelConfig:
    """Tests for ChannelConfig model."""

    def test_telegram_config(self):
        config = ChannelConfig(
            channel=NotificationChannel.TELEGRAM,
            telegram_chat_id="123456789",
        )
        assert config.channel == NotificationChannel.TELEGRAM
        assert config.enabled is True
        assert config.telegram_chat_id == "123456789"

    def test_webhook_config(self):
        config = ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            webhook_url="https://example.com/webhook",
        )
        assert config.webhook_url == "https://example.com/webhook"

    def test_quiet_hours(self):
        config = ChannelConfig(
            channel=NotificationChannel.PUSH,
            quiet_hours_start=22,
            quiet_hours_end=7,
        )
        assert config.quiet_hours_start == 22
        assert config.quiet_hours_end == 7


class TestNotificationPreferences:
    """Tests for NotificationPreferences model."""

    def test_defaults(self):
        prefs = NotificationPreferences(
            user_id=uuid4(),
            app_id=uuid4(),
        )
        assert prefs.enabled is True
        assert prefs.notify_on_complete is True
        assert prefs.notify_on_failure is True
        assert prefs.batch_low_priority is True

    def test_with_channels(self):
        prefs = NotificationPreferences(
            user_id=uuid4(),
            app_id=uuid4(),
            channels=[
                ChannelConfig(
                    channel=NotificationChannel.TELEGRAM,
                    telegram_chat_id="123",
                ),
                ChannelConfig(
                    channel=NotificationChannel.WEBHOOK,
                    webhook_url="https://example.com",
                ),
            ],
        )
        assert len(prefs.channels) == 2


class TestNotification:
    """Tests for Notification model."""

    def test_basic_notification(self):
        notif = Notification(
            type=NotificationType.TASK_COMPLETE,
            title="Task Done",
            body="Your task has completed successfully.",
        )
        assert notif.type == NotificationType.TASK_COMPLETE
        assert notif.priority == NotificationPriority.NORMAL
        assert notif.id is not None

    def test_full_notification(self):
        user_id = uuid4()
        app_id = uuid4()
        notif = Notification(
            user_id=user_id,
            app_id=app_id,
            type=NotificationType.TASK_FAILED,
            title="Task Failed",
            body="Error occurred",
            priority=NotificationPriority.HIGH,
            task_id="task-123",
            data={"error_code": 500},
            channels=[NotificationChannel.TELEGRAM],
        )
        assert notif.user_id == user_id
        assert notif.task_id == "task-123"
        assert NotificationChannel.TELEGRAM in notif.channels


class TestNotificationResult:
    """Tests for NotificationResult model."""

    def test_success_result(self):
        result = NotificationResult(
            notification_id=uuid4(),
            channel=NotificationChannel.TELEGRAM,
            success=True,
            external_id="msg_123",
        )
        assert result.success is True
        assert result.error_message is None

    def test_failure_result(self):
        result = NotificationResult(
            notification_id=uuid4(),
            channel=NotificationChannel.WEBHOOK,
            success=False,
            error_message="Connection refused",
        )
        assert result.success is False
        assert "Connection" in result.error_message


class TestTelegramNotifier:
    """Tests for TelegramNotifier."""

    def test_no_token(self):
        notifier = TelegramNotifier(bot_token=None)
        assert notifier.channel == NotificationChannel.TELEGRAM

    @pytest.mark.asyncio
    async def test_send_without_token(self):
        notifier = TelegramNotifier(bot_token=None)
        notification = Notification(
            type=NotificationType.TASK_COMPLETE,
            title="Test",
            body="Body",
        )
        config = ChannelConfig(
            channel=NotificationChannel.TELEGRAM,
            telegram_chat_id="123",
        )

        result = await notifier.send(notification, config)
        assert result.success is False
        assert "not configured" in result.error_message

    @pytest.mark.asyncio
    async def test_send_without_chat_id(self):
        notifier = TelegramNotifier(bot_token="test_token")
        notification = Notification(
            type=NotificationType.TASK_COMPLETE,
            title="Test",
            body="Body",
        )
        config = ChannelConfig(
            channel=NotificationChannel.TELEGRAM,
            telegram_chat_id=None,
        )

        result = await notifier.send(notification, config)
        assert result.success is False
        assert "chat_id" in result.error_message

    @pytest.mark.asyncio
    async def test_send_success(self):
        notifier = TelegramNotifier(bot_token="test_token")
        notification = Notification(
            type=NotificationType.TASK_COMPLETE,
            title="Test",
            body="Body",
        )
        config = ChannelConfig(
            channel=NotificationChannel.TELEGRAM,
            telegram_chat_id="123456",
        )

        # Mock httpx
        with patch("loop_symphony.services.notifier.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": {"message_id": 999}}

            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await notifier.send(notification, config)

            assert result.success is True
            assert result.external_id == "999"


class TestWebhookNotifier:
    """Tests for WebhookNotifier."""

    def test_channel(self):
        notifier = WebhookNotifier()
        assert notifier.channel == NotificationChannel.WEBHOOK

    @pytest.mark.asyncio
    async def test_send_without_url(self):
        notifier = WebhookNotifier()
        notification = Notification(
            type=NotificationType.TASK_COMPLETE,
            title="Test",
            body="Body",
        )
        config = ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            webhook_url=None,
        )

        result = await notifier.send(notification, config)
        assert result.success is False
        assert "URL not configured" in result.error_message

    @pytest.mark.asyncio
    async def test_send_success(self):
        notifier = WebhookNotifier()
        notification = Notification(
            type=NotificationType.TASK_COMPLETE,
            title="Test",
            body="Body",
            task_id="task-123",
        )
        config = ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            webhook_url="https://example.com/webhook",
        )

        with patch("loop_symphony.services.notifier.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await notifier.send(notification, config)

            assert result.success is True
            # Verify payload was correct
            call_args = mock_instance.post.call_args
            payload = call_args.kwargs["json"]
            assert payload["title"] == "Test"
            assert payload["task_id"] == "task-123"


class TestPushNotifier:
    """Tests for PushNotifier."""

    def test_channel(self):
        notifier = PushNotifier()
        assert notifier.channel == NotificationChannel.PUSH

    @pytest.mark.asyncio
    async def test_placeholder_returns_failure(self):
        notifier = PushNotifier()
        notification = Notification(
            type=NotificationType.TASK_COMPLETE,
            title="Test",
            body="Body",
        )
        config = ChannelConfig(
            channel=NotificationChannel.PUSH,
            push_device_token="abc123def456",
        )

        result = await notifier.send(notification, config)
        # Placeholder always returns failure
        assert result.success is False
        assert "placeholder" in result.error_message.lower()


class TestNotifier:
    """Tests for main Notifier class."""

    @pytest.mark.asyncio
    async def test_send_with_explicit_channels(self):
        notifier = Notifier()
        notification = Notification(
            type=NotificationType.SYSTEM_ALERT,
            title="Alert",
            body="System alert",
            channels=[NotificationChannel.WEBHOOK],
        )

        # No preferences needed when channels are explicit
        history = await notifier.send(notification)
        assert history.notification_id == notification.id
        assert history.type == NotificationType.SYSTEM_ALERT

    @pytest.mark.asyncio
    async def test_send_respects_preferences(self):
        notifier = Notifier()
        user_id = uuid4()
        app_id = uuid4()

        preferences = NotificationPreferences(
            user_id=user_id,
            app_id=app_id,
            channels=[
                ChannelConfig(
                    channel=NotificationChannel.WEBHOOK,
                    webhook_url="https://example.com",
                    enabled=True,
                ),
            ],
        )

        notification = Notification(
            user_id=user_id,
            app_id=app_id,
            type=NotificationType.TASK_COMPLETE,
            title="Done",
            body="Task complete",
        )

        with patch("loop_symphony.services.notifier.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            history = await notifier.send(notification, preferences)
            assert len(history.results) == 1
            assert history.results[0].channel == NotificationChannel.WEBHOOK

    @pytest.mark.asyncio
    async def test_send_task_complete_convenience(self):
        notifier = Notifier()
        user_id = uuid4()
        app_id = uuid4()

        history = await notifier.send_task_complete(
            user_id=user_id,
            app_id=app_id,
            task_id="task-123",
            summary="Research complete with high confidence",
            confidence=0.95,
        )

        assert history.type == NotificationType.TASK_COMPLETE
        assert history.title == "Task Complete"

    @pytest.mark.asyncio
    async def test_send_task_failed_convenience(self):
        notifier = Notifier()
        user_id = uuid4()
        app_id = uuid4()

        history = await notifier.send_task_failed(
            user_id=user_id,
            app_id=app_id,
            task_id="task-456",
            error_message="API timeout after 30 seconds",
        )

        assert history.type == NotificationType.TASK_FAILED
        assert "timeout" in history.body

    @pytest.mark.asyncio
    async def test_send_system_alert(self):
        notifier = Notifier()

        history = await notifier.send_system_alert(
            title="System Degraded",
            body="Database connection pool exhausted",
            priority=NotificationPriority.CRITICAL,
        )

        assert history.type == NotificationType.SYSTEM_ALERT

    @pytest.mark.asyncio
    async def test_get_history(self):
        notifier = Notifier()
        user_id = uuid4()

        # Send a few notifications
        for i in range(3):
            await notifier.send_system_alert(
                title=f"Alert {i}",
                body="Body",
            )

        history = notifier.get_history(limit=2)
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_disabled_preferences_no_send(self):
        notifier = Notifier()
        user_id = uuid4()
        app_id = uuid4()

        preferences = NotificationPreferences(
            user_id=user_id,
            app_id=app_id,
            enabled=False,  # Disabled
            channels=[
                ChannelConfig(
                    channel=NotificationChannel.WEBHOOK,
                    webhook_url="https://example.com",
                ),
            ],
        )

        notification = Notification(
            user_id=user_id,
            app_id=app_id,
            type=NotificationType.TASK_COMPLETE,
            title="Done",
            body="Complete",
        )

        history = await notifier.send(notification, preferences)
        # No channels should be used when disabled
        assert len(history.results) == 0

    @pytest.mark.asyncio
    async def test_notify_on_complete_disabled(self):
        notifier = Notifier()
        user_id = uuid4()
        app_id = uuid4()

        preferences = NotificationPreferences(
            user_id=user_id,
            app_id=app_id,
            notify_on_complete=False,  # Disabled for completions
            channels=[
                ChannelConfig(
                    channel=NotificationChannel.WEBHOOK,
                    webhook_url="https://example.com",
                ),
            ],
        )

        notification = Notification(
            user_id=user_id,
            app_id=app_id,
            type=NotificationType.TASK_COMPLETE,
            title="Done",
            body="Complete",
        )

        history = await notifier.send(notification, preferences)
        assert len(history.results) == 0


class TestNotificationHistory:
    """Tests for NotificationHistory model."""

    def test_basic_history(self):
        history = NotificationHistory(
            notification_id=uuid4(),
            type=NotificationType.TASK_COMPLETE,
            title="Test",
            body="Body",
        )
        assert history.id is not None
        assert len(history.results) == 0

    def test_history_with_results(self):
        notif_id = uuid4()
        history = NotificationHistory(
            notification_id=notif_id,
            type=NotificationType.TASK_COMPLETE,
            title="Test",
            body="Body",
            results=[
                NotificationResult(
                    notification_id=notif_id,
                    channel=NotificationChannel.TELEGRAM,
                    success=True,
                ),
                NotificationResult(
                    notification_id=notif_id,
                    channel=NotificationChannel.WEBHOOK,
                    success=False,
                    error_message="Connection refused",
                ),
            ],
        )
        assert len(history.results) == 2
        assert history.results[0].success is True
        assert history.results[1].success is False
