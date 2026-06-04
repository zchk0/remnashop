from dataclasses import dataclass

from .base import BaseDto, TimestampMixin, TrackableMixin


@dataclass(kw_only=True)
class AdLinkDto(BaseDto, TrackableMixin, TimestampMixin):
    name: str = ""
    code: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class AdLinkStatsDto:
    registrations: int
    conversions: int
    trials: int
    revenue: dict[str, float]

    @property
    def conversion_rate(self) -> float:
        if not self.registrations:
            return 0.0
        return round(self.conversions / self.registrations * 100, 1)
