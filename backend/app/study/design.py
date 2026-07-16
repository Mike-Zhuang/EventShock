"""确定性的全因子与 Latin hypercube 参数设计。"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass

from backend.app.study.models import (
    DesignCell,
    DesignKind,
    EvidenceBasis,
    ParameterSetting,
)


@dataclass(frozen=True, slots=True)
class FactorLevelSpec:
    parameterPath: str
    unit: str
    levels: tuple[float, ...]
    rationale: str
    evidenceBasis: EvidenceBasis = EvidenceBasis.ASSUMPTION
    sourceReference: str | None = None

    def __post_init__(self) -> None:
        normalized = _validatedNumericValues(self.levels, "levels")
        if len(normalized) < 2:
            raise ValueError("factor levels must contain at least 2 values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("factor levels must be unique")
        ParameterSetting(
            path=self.parameterPath,
            value=normalized[0],
            unit=self.unit,
            rationale=self.rationale,
            evidenceBasis=self.evidenceBasis,
            sourceReference=self.sourceReference,
        )
        object.__setattr__(self, "levels", tuple(sorted(normalized)))


@dataclass(frozen=True, slots=True)
class ParameterRangeSpec:
    parameterPath: str
    unit: str
    lower: float
    upper: float
    rationale: str
    evidenceBasis: EvidenceBasis = EvidenceBasis.ASSUMPTION
    sourceReference: str | None = None

    def __post_init__(self) -> None:
        lower, upper = _validatedNumericValues((self.lower, self.upper), "range")
        if lower >= upper:
            raise ValueError("parameter range lower must be smaller than upper")
        ParameterSetting(
            path=self.parameterPath,
            value=lower,
            unit=self.unit,
            rationale=self.rationale,
            evidenceBasis=self.evidenceBasis,
            sourceReference=self.sourceReference,
        )
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)


def generateFullFactorialCells(
    factors: tuple[FactorLevelSpec, ...],
    *,
    designId: str = "factorial",
    maximumCells: int = 10_000,
) -> tuple[DesignCell, ...]:
    """生成完整笛卡尔积，输入顺序不影响结果。"""

    ordered = _validatedFactors(factors)
    _validateMaximumCells(maximumCells)
    cellCount = math.prod(len(factor.levels) for factor in ordered)
    if cellCount > maximumCells:
        raise ValueError(
            f"full factorial design would create {cellCount} cells, above {maximumCells}"
        )
    cells = []
    for index, values in enumerate(
        itertools.product(*(factor.levels for factor in ordered)),
    ):
        settings = tuple(
            _settingFromFactor(factor, value) for factor, value in zip(ordered, values, strict=True)
        )
        cells.append(
            DesignCell(
                cellId=f"{designId}-{index:04d}",
                designKind=DesignKind.FULL_FACTORIAL,
                settings=settings,
                designIndex=index,
            )
        )
    return tuple(cells)


def generateLatinHypercubeCells(
    ranges: tuple[ParameterRangeSpec, ...],
    *,
    sampleCount: int,
    seed: int,
    designId: str = "lhs",
    maximumCells: int = 10_000,
) -> tuple[DesignCell, ...]:
    """在每个参数维度各取一次每个分层，且仅使用局部随机流。"""

    ordered = _validatedRanges(ranges)
    _validateMaximumCells(maximumCells)
    if isinstance(sampleCount, bool) or not isinstance(sampleCount, int) or sampleCount < 3:
        raise ValueError("sampleCount must be an integer of at least 3")
    if sampleCount > maximumCells:
        raise ValueError("sampleCount exceeds maximumCells")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    randomStream = random.Random(seed)
    valuesByPath: dict[str, tuple[float, ...]] = {}
    for parameterRange in ordered:
        strata = list(range(sampleCount))
        randomStream.shuffle(strata)
        samples = []
        for stratum in strata:
            quantile = (stratum + randomStream.random()) / sampleCount
            samples.append(
                parameterRange.lower + quantile * (parameterRange.upper - parameterRange.lower)
            )
        valuesByPath[parameterRange.parameterPath] = tuple(samples)

    return tuple(
        DesignCell(
            cellId=f"{designId}-{index:04d}",
            designKind=DesignKind.LATIN_HYPERCUBE,
            settings=tuple(
                _settingFromRange(
                    parameterRange,
                    valuesByPath[parameterRange.parameterPath][index],
                )
                for parameterRange in ordered
            ),
            designIndex=index,
        )
        for index in range(sampleCount)
    )


def _settingFromFactor(factor: FactorLevelSpec, value: float) -> ParameterSetting:
    return ParameterSetting(
        path=factor.parameterPath,
        value=value,
        unit=factor.unit,
        rationale=factor.rationale,
        evidenceBasis=factor.evidenceBasis,
        sourceReference=factor.sourceReference,
    )


def _settingFromRange(parameterRange: ParameterRangeSpec, value: float) -> ParameterSetting:
    return ParameterSetting(
        path=parameterRange.parameterPath,
        value=value,
        unit=parameterRange.unit,
        rationale=parameterRange.rationale,
        evidenceBasis=parameterRange.evidenceBasis,
        sourceReference=parameterRange.sourceReference,
    )


def _validatedFactors(factors: tuple[FactorLevelSpec, ...]) -> tuple[FactorLevelSpec, ...]:
    if not factors:
        raise ValueError("factors must not be empty")
    ordered = tuple(sorted(factors, key=lambda factor: factor.parameterPath))
    if len({factor.parameterPath for factor in ordered}) != len(ordered):
        raise ValueError("factor parameter paths must be unique")
    return ordered


def _validatedRanges(
    ranges: tuple[ParameterRangeSpec, ...],
) -> tuple[ParameterRangeSpec, ...]:
    if not ranges:
        raise ValueError("ranges must not be empty")
    ordered = tuple(sorted(ranges, key=lambda item: item.parameterPath))
    if len({item.parameterPath for item in ordered}) != len(ordered):
        raise ValueError("range parameter paths must be unique")
    return ordered


def _validatedNumericValues(values: tuple[float, ...], name: str) -> tuple[float, ...]:
    normalized = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{name} must contain only numeric values")
        normalizedValue = float(value)
        if not math.isfinite(normalizedValue):
            raise ValueError(f"{name} must contain only finite values")
        normalized.append(normalizedValue)
    return tuple(normalized)


def _validateMaximumCells(maximumCells: int) -> None:
    if isinstance(maximumCells, bool) or not isinstance(maximumCells, int) or maximumCells < 1:
        raise ValueError("maximumCells must be a positive integer")
