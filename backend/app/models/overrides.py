"""Strict nested request models for per-request valuation overrides."""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


class OverrideValidationError(ValueError):
    """An override is syntactically valid JSON but violates model policy."""


def _decimal_number(value: object, field_name: str) -> Decimal:
    """Accept JSON numbers/Decimal only; reject strings, bool and nonfinite."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{field_name} must be a finite JSON number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


class _ScenarioOverride(BaseModel):
    low: Optional[Decimal] = None
    base: Optional[Decimal] = None
    high: Optional[Decimal] = None

    model_config = {"extra": "forbid"}


class PEOverride(_ScenarioOverride):
    @field_validator("low", "base", "high", mode="before")
    @classmethod
    def _range(cls, value: object, info) -> Decimal | None:
        if value is None:
            return None
        result = _decimal_number(value, f"forward_pe.{info.field_name}")
        if not (Decimal("0") < result <= Decimal("200")):
            raise ValueError("P/E multiple must be greater than 0 and at most 200")
        return result

    @model_validator(mode="after")
    def _provided_order(self) -> "PEOverride":
        values = [value for value in (self.low, self.base, self.high) if value is not None]
        if len(values) > 1 and values != sorted(values):
            raise ValueError("P/E multiples must satisfy low <= base <= high")
        return self


class EVEBITDAOverride(_ScenarioOverride):
    @field_validator("low", "base", "high", mode="before")
    @classmethod
    def _range(cls, value: object, info) -> Decimal | None:
        if value is None:
            return None
        result = _decimal_number(value, f"ev_ebitda.{info.field_name}")
        if not (Decimal("0") < result <= Decimal("200")):
            raise ValueError("EV/EBITDA multiple must be greater than 0 and at most 200")
        return result

    @model_validator(mode="after")
    def _provided_order(self) -> "EVEBITDAOverride":
        values = [value for value in (self.low, self.base, self.high) if value is not None]
        if len(values) > 1 and values != sorted(values):
            raise ValueError("EV/EBITDA multiples must satisfy low <= base <= high")
        return self


class FCFYieldOverride(_ScenarioOverride):
    @field_validator("low", "base", "high", mode="before")
    @classmethod
    def _range(cls, value: object, info) -> Decimal | None:
        if value is None:
            return None
        result = _decimal_number(value, f"fcf_yield.{info.field_name}")
        if not (Decimal("0") < result <= Decimal("0.5")):
            raise ValueError("FCF yield must be greater than 0 and at most 0.5")
        return result

    @model_validator(mode="after")
    def _provided_inverse_order(self) -> "FCFYieldOverride":
        # low is the conservative/high-yield rate; high is the
        # optimistic/low-yield rate.
        if self.low is not None and self.high is not None and self.low < self.high:
            raise ValueError("FCF yield must satisfy low >= high")
        if self.base is not None and self.low is not None and self.base > self.low:
            raise ValueError("FCF yield must satisfy base <= low")
        if self.base is not None and self.high is not None and self.base < self.high:
            raise ValueError("FCF yield must satisfy base >= high")
        return self


class DCFOverride(BaseModel):
    wacc: Optional[Decimal] = None
    terminal_growth: Optional[Decimal] = None
    fcf_growth: Optional[Decimal] = None

    model_config = {"extra": "forbid"}

    @field_validator("wacc", "terminal_growth", "fcf_growth", mode="before")
    @classmethod
    def _finite(cls, value: object, info) -> Decimal | None:
        if value is None:
            return None
        result = _decimal_number(value, f"dcf.{info.field_name}")
        if info.field_name == "wacc" and not (Decimal("0") < result <= Decimal("0.5")):
            raise ValueError("WACC must be greater than 0 and at most 0.5")
        if info.field_name == "terminal_growth" and not (Decimal("0") <= result <= Decimal("0.05")):
            raise ValueError("terminal_growth must be between 0 and 0.05")
        if info.field_name == "fcf_growth" and not (Decimal("-0.5") <= result <= Decimal("0.5")):
            raise ValueError("fcf_growth must be between -0.5 and 0.5")
        return result

    @model_validator(mode="after")
    def _provided_wacc_order(self) -> "DCFOverride":
        if self.wacc is not None and self.terminal_growth is not None and self.wacc <= self.terminal_growth:
            raise ValueError("WACC must be greater than terminal_growth")
        return self


class ValuationOverrideRequest(BaseModel):
    """The public POST contract; all unknown keys are rejected."""

    forward_pe: Optional[PEOverride] = None
    ev_ebitda: Optional[EVEBITDAOverride] = None
    fcf_yield: Optional[FCFYieldOverride] = None
    dcf: Optional[DCFOverride] = None

    model_config = {"extra": "forbid"}

    def to_override_dict(self) -> dict[str, Decimal]:
        """Flatten the request while deriving sparse scenario bounds."""

        result: dict[str, Decimal] = {}

        def put_scenarios(
            prefix: str,
            value: _ScenarioOverride,
            inverse: bool = False,
            maximum: Decimal | None = None,
        ) -> None:
            if value.base is not None:
                result[f"{prefix}.base"] = value.base
                low_default = value.base * (Decimal("1.1") if inverse else Decimal("0.9"))
                high_default = value.base * (Decimal("0.9") if inverse else Decimal("1.1"))
                result[f"{prefix}.low"] = value.low if value.low is not None else low_default
                result[f"{prefix}.high"] = value.high if value.high is not None else high_default
                if maximum is not None and any(
                    bound > maximum
                    for bound in (result[f"{prefix}.low"], result[f"{prefix}.base"], result[f"{prefix}.high"])
                ):
                    raise ValueError(f"{prefix} effective values must be <= {maximum}")
            else:
                if value.low is not None:
                    result[f"{prefix}.low"] = value.low
                if value.high is not None:
                    result[f"{prefix}.high"] = value.high

        if self.forward_pe is not None:
            put_scenarios("forward_pe", self.forward_pe, maximum=Decimal("200"))
        if self.ev_ebitda is not None:
            put_scenarios("ev_ebitda", self.ev_ebitda, maximum=Decimal("200"))
        if self.fcf_yield is not None:
            put_scenarios("fcf_yield", self.fcf_yield, inverse=True, maximum=Decimal("0.5"))
        if self.dcf is not None:
            if self.dcf.wacc is not None:
                result["dcf.wacc"] = self.dcf.wacc
            if self.dcf.terminal_growth is not None:
                result["dcf.terminal_growth"] = self.dcf.terminal_growth
            if self.dcf.fcf_growth is not None:
                result["dcf.fcf_growth"] = self.dcf.fcf_growth
        return result
