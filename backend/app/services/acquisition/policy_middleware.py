from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.acquisition.rate_limiter import record_fetch_outcome
from app.services.acquisition.rate_limiter import wait_for_host_slot

if TYPE_CHECKING:
    from app.services.acquisition.acquirer import AcquisitionRequest, AcquisitionResult


@dataclass(slots=True)
class PolicyDecision:
    stage: str
    action: str
    reason: str
    url: str

    def as_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "action": self.action,
            "reason": self.reason,
            "url": self.url,
        }


@dataclass(slots=True)
class PolicyMiddleware:
    decisions: list[PolicyDecision] = field(default_factory=list)

    async def before_fetch(self, request: AcquisitionRequest) -> None:
        await wait_for_host_slot(
            request.url,
            ttl_seconds=request.policy.host_memory_ttl_seconds if request.policy else None,
        )
        self._record("pre_fetch", "paced", "domain_rate_limiter", request.url)

    async def after_fetch(self, result: AcquisitionResult) -> None:
        backoff_applied = await record_fetch_outcome(
            result.final_url or result.request.url,
            status_code=result.status_code,
            blocked=result.blocked,
            ttl_seconds=result.request.policy.host_memory_ttl_seconds
            if result.request.policy
            else None,
        )
        if backoff_applied:
            self._record(
                "post_fetch",
                "backoff",
                "blocked_or_retryable_status",
                result.final_url or result.request.url,
            )
        result.browser_diagnostics = {
            **dict(result.browser_diagnostics or {}),
            "policy_decisions": [decision.as_dict() for decision in self.decisions],
        }

    def _record(self, stage: str, action: str, reason: str, url: str) -> None:
        self.decisions.append(
            PolicyDecision(stage=stage, action=action, reason=reason, url=url)
        )
