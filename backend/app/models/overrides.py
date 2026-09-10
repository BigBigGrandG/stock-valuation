"""Strict nested request models for per-request valuation overrides."""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Literal, Optional

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
    growth_floor: Optional[Decimal] = None
    growth_cap: Optional[Decimal] = None

    model_config = {"extra": "forbid"}

    @field_validator("wacc", "terminal_growth", "fcf_growth", "growth_floor", "growth_cap", mode="before")
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
        if info.field_name == "growth_floor" and not (Decimal("-1.0") < result <= Decimal("2.0")):
            raise ValueError("growth_floor must be greater than -1.0 and at most 2.0")
        if info.field_name == "growth_cap" and not (Decimal("-1.0") < result <= Decimal("2.0")):
            raise ValueError("growth_cap must be greater than -1.0 and at most 2.0")
        return result

    @model_validator(mode="after")
    def _provided_wacc_order(self) -> "DCFOverride":
        if self.wacc is not None and self.terminal_growth is not None and self.wacc <= self.terminal_growth:
            raise ValueError("WACC must be greater than terminal_growth")
        eff_floor = self.growth_floor if self.growth_floor is not None else Decimal("-0.20")
        eff_cap = self.growth_cap if self.growth_cap is not None else Decimal("0.40")
        if eff_floor > eff_cap:
            raise ValueError("growth_floor must be <= growth_cap")
        return self


class WeightOverride(BaseModel):
    weight_pe: Optional[Decimal] = None
    weight_ev_ebitda: Optional[Decimal] = None
    weight_fcf_yield: Optional[Decimal] = None
    weight_dcf: Optional[Decimal] = None
    cashflow_group_max_weight: Optional[Decimal] = None

    model_config = {"extra": "forbid"}

    @field_validator(
        "weight_pe",
        "weight_ev_ebitda",
        "weight_fcf_yield",
        "weight_dcf",
        "cashflow_group_max_weight",
        mode="before",
    )
    @classmethod
    def _validate_weights(cls, value: object, info) -> Decimal | None:
        if value is None:
            return None
        result = _decimal_number(value, f"weights.{info.field_name}")
        if result < Decimal("0"):
            raise ValueError(f"{info.field_name} must be non-negative")
        if info.field_name == "cashflow_group_max_weight" and result > Decimal("1.0"):
            raise ValueError("cashflow_group_max_weight must be between 0 and 1.0")
        if info.field_name != "cashflow_group_max_weight" and result > Decimal("10.0"):
            raise ValueError(f"{info.field_name} must be at most 10.0")
        return result

    @model_validator(mode="after")
    def _check_at_least_one_positive(self) -> "WeightOverride":
        eff_pe = self.weight_pe if self.weight_pe is not None else Decimal("0.25")
        eff_ev = self.weight_ev_ebitda if self.weight_ev_ebitda is not None else Decimal("0.20")
        eff_fcf = self.weight_fcf_yield if self.weight_fcf_yield is not None else Decimal("0.25")
        eff_dcf = self.weight_dcf if self.weight_dcf is not None else Decimal("0.30")
        merged = [eff_pe, eff_ev, eff_fcf, eff_dcf]
        if all(w <= Decimal("0") for w in merged):
            raise ValueError("At least one model weight must be greater than 0")
        return self


class ValuationOverrideRequest(BaseModel):
    """The public POST contract; all unknown keys are rejected."""

    forward_pe: Optional[PEOverride] = None
    ev_ebitda: Optional[EVEBITDAOverride] = None
    fcf_yield: Optional[FCFYieldOverride] = None
    dcf: Optional[DCFOverride] = None
    weights: Optional[WeightOverride] = None
    forecast_horizon: Optional[Literal["ntm", "current_fy", "next_fy"]] = None

    model_config = {"extra": "forbid"}

    def to_override_dict(self) -> dict[str, Any]:
        """Flatten the request while deriving sparse scenario bounds."""

        result: dict[str, Any] = {}

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
            if self.dcf.growth_floor is not None:
                result["dcf.growth_floor"] = self.dcf.growth_floor
            if self.dcf.growth_cap is not None:
                result["dcf.growth_cap"] = self.dcf.growth_cap
        if self.weights is not None:
            if self.weights.weight_pe is not None:
                result["weights.weight_pe"] = self.weights.weight_pe
            if self.weights.weight_ev_ebitda is not None:
                result["weights.weight_ev_ebitda"] = self.weights.weight_ev_ebitda
            if self.weights.weight_fcf_yield is not None:
                result["weights.weight_fcf_yield"] = self.weights.weight_fcf_yield
            if self.weights.weight_dcf is not None:
                result["weights.weight_dcf"] = self.weights.weight_dcf
            if self.weights.cashflow_group_max_weight is not None:
                result["weights.cashflow_group_max_weight"] = self.weights.cashflow_group_max_weight
        if self.forecast_horizon is not None:
            result["forecast_horizon"] = self.forecast_horizon
        return result
