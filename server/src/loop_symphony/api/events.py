"""In-memory per-task event pub/sub for SSE streaming."""

from __future__ import annotations

import asyncio
import time
from typing import Any

# Event type constants
EVENT_STARTED = "started"
EVENT_ITERATION = "iteration"
EVENT_COMPLETE = "complete"
EVENT_ERROR = "error"
_TERMINAL_EVENTS = frozenset({EVENT_COMPLETE, EVENT_ERROR})


class EventBus:
    """In-memory event bus for broadcasting task events to SSE subscribers.

    Each task has its own event history and set of subscriber queues.
    Late joiners receive the full event history before live events.
    """

    def __init__(self, history_ttl: float = 300) -> None:
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._completed_at: dict[str, float] = {}
        self._history_ttl = history_ttl

    def emit(self, task_id: str, event: dict[str, Any]) -> None:
        """Emit an event for a task.

        Appends to history, stamps with task_id and timestamp,
        and pushes to all subscriber queues (non-blocking).
        """
        event = {**event, "task_id": task_id, "timestamp": time.time()}

        if task_id not in self._events:
            self._events[task_id] = []
        self._events[task_id].append(event)

        # Mark completion time for TTL cleanup
        if event.get("event") in _TERMINAL_EVENTS:
            self._completed_at[task_id] = time.monotonic()

        # Push to all subscriber queues
        for queue in self._subscribers.get(task_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop event if subscriber is too slow

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to events for a task.

        Returns a queue pre-populated with existing event history.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)

        # Pre-populate with history
        for event in self._events.get(task_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                break

        if task_id not in self._subscribers:
            self._subscribers[task_id] = []
        self._subscribers[task_id].append(queue)

        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue. Idempotent."""
        subscribers = self._subscribers.get(task_id, [])
        try:
            subscribers.remove(queue)
        except ValueError:
            pass

    def has_terminal_event(self, task_id: str) -> bool:
        """Check if a terminal event (complete/error) has been emitted."""
        for event in self._events.get(task_id, []):
            if event.get("event") in _TERMINAL_EVENTS:
                return True
        return False

    def cleanup_stale(self) -> int:
        """Remove event data for tasks past the history TTL.

        Returns the number of tasks cleaned up.
        """
        now = time.monotonic()
        stale = [
            task_id
            for task_id, completed_at in self._completed_at.items()
            if now - completed_at > self._history_ttl
        ]
        for task_id in stale:
            self._events.pop(task_id, None)
            self._subscribers.pop(task_id, None)
            self._completed_at.pop(task_id, None)
        return len(stale)
