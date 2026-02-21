"""Approval routing for governance flow."""

from datetime import datetime, UTC
from uuid import UUID

from librarian.models.approval_request import ApprovalRequest, ApprovalStatus


class ApprovalRouter:
    """Manages pending approval requests in memory."""

    def __init__(self) -> None:
        self._requests: dict[UUID, ApprovalRequest] = {}

    def submit(self, request: ApprovalRequest) -> ApprovalRequest:
        """Store a new approval request and return it."""
        self._requests[request.id] = request
        self._notify(request)
        return request

    def resolve(
        self, request_id: UUID, approved: bool, resolved_by: str
    ) -> ApprovalRequest:
        """Approve or deny a pending request."""
        request = self._requests.get(request_id)
        if request is None:
            raise KeyError(f"Approval request {request_id} not found")

        request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        request.resolved_at = datetime.now(UTC)
        request.resolved_by = resolved_by
        return request

    def get_pending(
        self, conductor_id: str | None = None
    ) -> list[ApprovalRequest]:
        """Return all pending requests, optionally filtered by conductor_id."""
        pending = [
            r
            for r in self._requests.values()
            if r.status == ApprovalStatus.PENDING
        ]
        if conductor_id is not None:
            pending = [r for r in pending if r.conductor_id == conductor_id]
        return pending

    def expire_stale(self) -> list[ApprovalRequest]:
        """Mark and return requests that have exceeded their TTL."""
        now = datetime.now(UTC)
        expired: list[ApprovalRequest] = []
        for request in self._requests.values():
            if request.status != ApprovalStatus.PENDING:
                continue
            elapsed = (now - request.requested_at).total_seconds()
            if elapsed > request.ttl_seconds:
                request.status = ApprovalStatus.EXPIRED
                request.resolved_at = now
                expired.append(request)
        return expired

    def get(self, request_id: UUID) -> ApprovalRequest | None:
        """Look up a request by ID."""
        return self._requests.get(request_id)

    def _notify(self, request: ApprovalRequest) -> None:
        """Notify interested parties of a new approval request.

        This is a no-op stub; Dispatch integration comes later.
        """
        pass
