from dataclasses import dataclass
from html import escape
from math import isfinite
from typing import Any, Final

import httpx

from src.core.enums import PaymentGatewayType

PAYMENT_GATEWAY_EXTENSION: Final[str] = "remnashop.payment_gateway"
_TIMEOUT_PHASES: Final[tuple[tuple[type[httpx.TimeoutException], str], ...]] = (
    (httpx.ConnectTimeout, "connect"),
    (httpx.ReadTimeout, "read"),
    (httpx.WriteTimeout, "write"),
    (httpx.PoolTimeout, "pool"),
)


@dataclass(frozen=True)
class PaymentGatewayTimeout:
    gateway_type: PaymentGatewayType
    error_type: str
    phase: str
    method: str
    host: str
    timeout_seconds: float | None

    def attach_to(self, exception: BaseException) -> None:
        setattr(exception, "_payment_gateway_timeout", self)

    def as_i18n_kwargs(self) -> dict[str, Any]:
        return {
            "gateway_type": self.gateway_type.value,
            "timeout_type": escape(self.error_type),
            "timeout_phase": self.phase,
            "request_method": escape(self.method),
            "request_host": escape(self.host),
            "has_timeout": self.timeout_seconds is not None,
            "timeout_seconds": self.timeout_seconds if self.timeout_seconds is not None else 0,
        }

    def as_text(self) -> str:
        text = (
            f"Payment gateway: {self.gateway_type.value}\n"
            f"Reason: {self.error_type} ({self.phase} timeout)\n"
            f"Request: {self.method} {self.host}\n"
        )
        if self.timeout_seconds is not None:
            text += f"Timeout limit: {self.timeout_seconds:g} s\n"
        return text


def find_payment_gateway_timeout(exception: BaseException) -> PaymentGatewayTimeout | None:
    current: BaseException | None = exception
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        attached = getattr(current, "_payment_gateway_timeout", None)
        if isinstance(attached, PaymentGatewayTimeout):
            return attached
        if isinstance(current, httpx.TimeoutException):
            try:
                request = current.request
            except RuntimeError:
                request = None
            if request is not None:
                raw_gateway = request.extensions.get(PAYMENT_GATEWAY_EXTENSION)
                try:
                    gateway_type = (
                        PaymentGatewayType(raw_gateway) if isinstance(raw_gateway, str) else None
                    )
                except (TypeError, ValueError):
                    gateway_type = None
                if gateway_type is not None:
                    phase = next(
                        (name for kind, name in _TIMEOUT_PHASES if isinstance(current, kind)),
                        "request",
                    )
                    timeouts = request.extensions.get("timeout")
                    limit = timeouts.get(phase) if isinstance(timeouts, dict) else None
                    timeout_seconds = (
                        float(limit)
                        if isinstance(limit, (int, float))
                        and not isinstance(limit, bool)
                        and isfinite(limit)
                        and limit >= 0
                        else None
                    )
                    return PaymentGatewayTimeout(
                        gateway_type=gateway_type,
                        error_type=type(current).__name__,
                        phase=phase,
                        method=request.method,
                        # URLs may contain credentials, tokens, or customer data.
                        # The API host is enough to identify the failing service.
                        host=request.url.host or "—",
                        timeout_seconds=timeout_seconds,
                    )
        current = current.__cause__ or current.__context__
    return None
