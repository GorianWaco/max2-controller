"""Wspólny interfejs backendów."""

from __future__ import annotations

from typing import Protocol

from max2_controller.models import CommandResult, ToyInfo


class ToyBackend(Protocol):
    def get_toys(self) -> tuple[list[ToyInfo], CommandResult]: ...
    def set_vibrate(self, level: int, time_sec: float = 0, toy: str | None = None, **kwargs) -> CommandResult: ...
    def set_pump(self, level: int, time_sec: float = 0, toy: str | None = None, **kwargs) -> CommandResult: ...
    def set_both(
        self, vibrate: int, pump: int, time_sec: float = 0, toy: str | None = None, **kwargs
    ) -> CommandResult: ...
    def stop(self, toy: str | None = None) -> CommandResult: ...
    def preset(self, name: str, time_sec: float = 0, toy: str | None = None) -> CommandResult: ...
    def pattern(
        self,
        strength: str,
        time_sec: float = 0,
        toy: str | None = None,
        interval_ms: int = 200,
        features: str = "v,p",
        **kwargs,
    ) -> CommandResult: ...
    def get_battery(self, toy: str | None = None) -> tuple[int | None, CommandResult]: ...
