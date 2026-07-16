"""仅使用标准库的确定性配对实验统计工具。

模块面向 matched-seed 反事实实验。所有函数先拒绝 NaN、无穷和长度不一致，
bootstrap 使用局部、显式 seed，不受进程级随机状态影响。
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

Statistic = Callable[[Sequence[float]], float]


class TailDirection(StrEnum):
    GREATER_EQUAL = "GREATER_EQUAL"
    LESS_EQUAL = "LESS_EQUAL"
    ABSOLUTE = "ABSOLUTE"


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    estimate: float
    lower: float
    upper: float
    confidenceLevel: float
    resamples: int
    seed: int
    statisticName: str

    @property
    def containsZero(self) -> bool:
        return self.lower <= 0.0 <= self.upper


@dataclass(frozen=True, slots=True)
class EffectSizeResult:
    meanDifference: float
    standardDeviationDifference: float
    cohensDz: float | None
    matchedRankBiserial: float


@dataclass(frozen=True, slots=True)
class TailProbabilityResult:
    threshold: float
    direction: TailDirection
    exceedanceCount: int
    sampleSize: int
    probability: float


@dataclass(frozen=True, slots=True)
class HolmResult:
    hypothesisId: str
    rawPValue: float
    adjustedPValue: float
    alphaThreshold: float
    rejected: bool
    rank: int


@dataclass(frozen=True, slots=True)
class SensitivityIndex:
    parameter: str
    spearmanCorrelation: float
    direction: str
    varianceImportanceProxy: float
    sampleSize: int


@dataclass(frozen=True, slots=True)
class PairedAnalysis:
    sampleSize: int
    meanDifference: float
    medianDifference: float
    percentileLower: float
    percentileUpper: float
    bootstrap95: BootstrapInterval
    effectSize: EffectSizeResult
    signConsistency: float
    positiveTailProbability: float
    negativeTailProbability: float
    differences: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class NegativeControlResult:
    controlName: str
    tolerance: float
    analysis: PairedAnalysis
    passed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class KnockoutResult:
    knockoutName: str
    fullEffect: float
    knockoutEffect: float
    attenuationFraction: float | None
    attenuationInterval: BootstrapInterval
    minimumAttenuationFraction: float
    mechanismSupported: bool


def pairedDifferences(
    baseline: Sequence[float],
    intervention: Sequence[float],
) -> tuple[float, ...]:
    baselineValues = _validatedValues(baseline, "baseline", minimumSize=2)
    interventionValues = _validatedValues(
        intervention,
        "intervention",
        minimumSize=2,
    )
    if len(baselineValues) != len(interventionValues):
        raise ValueError("baseline and intervention must have equal lengths")
    return tuple(
        interventionValue - baselineValue
        for baselineValue, interventionValue in zip(
            baselineValues,
            interventionValues,
            strict=True,
        )
    )


def bootstrap95ConfidenceInterval(
    values: Sequence[float],
    *,
    statistic: Statistic = statistics.fmean,
    statisticName: str = "mean",
    resamples: int = 5_000,
    seed: int = 0,
) -> BootstrapInterval:
    """返回 percentile bootstrap 95% 区间。"""

    sample = _validatedValues(values, "values", minimumSize=2)
    if resamples < 100:
        raise ValueError("resamples must be at least 100")
    if not statisticName:
        raise ValueError("statisticName must not be empty")
    estimate = float(statistic(sample))
    if not math.isfinite(estimate):
        raise ValueError("statistic returned a non-finite estimate")

    randomStream = random.Random(seed)
    sampleSize = len(sample)
    bootstrapEstimates = []
    for _ in range(resamples):
        resample = tuple(sample[randomStream.randrange(sampleSize)] for _ in range(sampleSize))
        resampledEstimate = float(statistic(resample))
        if not math.isfinite(resampledEstimate):
            raise ValueError("statistic returned a non-finite bootstrap estimate")
        bootstrapEstimates.append(resampledEstimate)
    bootstrapEstimates.sort()
    return BootstrapInterval(
        estimate=estimate,
        lower=_quantile(bootstrapEstimates, 0.025),
        upper=_quantile(bootstrapEstimates, 0.975),
        confidenceLevel=0.95,
        resamples=resamples,
        seed=seed,
        statisticName=statisticName,
    )


def pairedEffectSize(
    baseline: Sequence[float],
    intervention: Sequence[float],
) -> EffectSizeResult:
    differences = pairedDifferences(baseline, intervention)
    meanDifference = statistics.fmean(differences)
    standardDeviation = statistics.stdev(differences)
    cohensDz = meanDifference / standardDeviation if standardDeviation > 0 else None
    positiveCount = sum(value > 0 for value in differences)
    negativeCount = sum(value < 0 for value in differences)
    nonZeroCount = positiveCount + negativeCount
    matchedRankBiserial = (positiveCount - negativeCount) / nonZeroCount if nonZeroCount else 0.0
    return EffectSizeResult(
        meanDifference=meanDifference,
        standardDeviationDifference=standardDeviation,
        cohensDz=cohensDz,
        matchedRankBiserial=matchedRankBiserial,
    )


def empiricalTailProbability(
    values: Sequence[float],
    *,
    threshold: float,
    direction: TailDirection,
) -> TailProbabilityResult:
    sample = _validatedValues(values, "values", minimumSize=1)
    if not math.isfinite(threshold) or threshold < 0 and direction is TailDirection.ABSOLUTE:
        raise ValueError("threshold must be finite and non-negative for ABSOLUTE tails")
    if direction is TailDirection.GREATER_EQUAL:
        exceedanceCount = sum(value >= threshold for value in sample)
    elif direction is TailDirection.LESS_EQUAL:
        exceedanceCount = sum(value <= threshold for value in sample)
    else:
        exceedanceCount = sum(abs(value) >= threshold for value in sample)
    return TailProbabilityResult(
        threshold=threshold,
        direction=direction,
        exceedanceCount=exceedanceCount,
        sampleSize=len(sample),
        probability=exceedanceCount / len(sample),
    )


def holmBonferroni(
    pValues: Mapping[str, float],
    *,
    alpha: float = 0.05,
) -> tuple[HolmResult, ...]:
    """对一个预注册假设家族执行 Holm step-down 校正。"""

    if not pValues:
        raise ValueError("pValues must not be empty")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    for hypothesisId, pValue in pValues.items():
        if not hypothesisId:
            raise ValueError("hypothesis IDs must not be empty")
        if not math.isfinite(pValue) or not 0.0 <= pValue <= 1.0:
            raise ValueError(f"invalid p-value for {hypothesisId}")

    ordered = sorted(pValues.items(), key=lambda item: (item[1], item[0]))
    familySize = len(ordered)
    adjustedById: dict[str, float] = {}
    runningAdjusted = 0.0
    rejectionStillOpen = True
    rejectedById: dict[str, bool] = {}
    thresholdById: dict[str, float] = {}
    for zeroBasedRank, (hypothesisId, pValue) in enumerate(ordered):
        remaining = familySize - zeroBasedRank
        runningAdjusted = max(runningAdjusted, min(1.0, remaining * pValue))
        adjustedById[hypothesisId] = runningAdjusted
        threshold = alpha / remaining
        thresholdById[hypothesisId] = threshold
        rejected = rejectionStillOpen and pValue <= threshold
        rejectedById[hypothesisId] = rejected
        if not rejected:
            rejectionStillOpen = False

    return tuple(
        HolmResult(
            hypothesisId=hypothesisId,
            rawPValue=pValue,
            adjustedPValue=adjustedById[hypothesisId],
            alphaThreshold=thresholdById[hypothesisId],
            rejected=rejectedById[hypothesisId],
            rank=rank,
        )
        for rank, (hypothesisId, pValue) in enumerate(ordered, start=1)
    )


def rankCorrelationSensitivity(
    parameterSamples: Mapping[str, Sequence[float]],
    outcomes: Sequence[float],
) -> tuple[SensitivityIndex, ...]:
    """用 Spearman 相关做全局初筛，并归一化平方相关作为重要性代理。"""

    if not parameterSamples:
        raise ValueError("parameterSamples must not be empty")
    outcomeValues = _validatedValues(outcomes, "outcomes", minimumSize=3)
    correlations: dict[str, float] = {}
    for parameter, values in parameterSamples.items():
        if not parameter:
            raise ValueError("parameter names must not be empty")
        parameterValues = _validatedValues(
            values,
            f"parameter {parameter}",
            minimumSize=3,
        )
        if len(parameterValues) != len(outcomeValues):
            raise ValueError(f"parameter {parameter} has a different sample length")
        correlations[parameter] = _pearsonCorrelation(
            _averageRanks(parameterValues),
            _averageRanks(outcomeValues),
        )
    squaredTotal = sum(value * value for value in correlations.values())
    return tuple(
        SensitivityIndex(
            parameter=parameter,
            spearmanCorrelation=correlation,
            direction=(
                "POSITIVE" if correlation > 0 else "NEGATIVE" if correlation < 0 else "FLAT"
            ),
            varianceImportanceProxy=(
                correlation * correlation / squaredTotal if squaredTotal else 0.0
            ),
            sampleSize=len(outcomeValues),
        )
        for parameter, correlation in sorted(
            correlations.items(),
            key=lambda item: (-abs(item[1]), item[0]),
        )
    )


def analyzePairedExperiment(
    baseline: Sequence[float],
    intervention: Sequence[float],
    *,
    bootstrapResamples: int = 5_000,
    seed: int = 0,
) -> PairedAnalysis:
    differences = pairedDifferences(baseline, intervention)
    meanDifference = statistics.fmean(differences)
    if meanDifference > 0:
        signConsistency = sum(value > 0 for value in differences) / len(differences)
    elif meanDifference < 0:
        signConsistency = sum(value < 0 for value in differences) / len(differences)
    else:
        signConsistency = sum(value == 0 for value in differences) / len(differences)
    return PairedAnalysis(
        sampleSize=len(differences),
        meanDifference=meanDifference,
        medianDifference=statistics.median(differences),
        percentileLower=_quantile(sorted(differences), 0.025),
        percentileUpper=_quantile(sorted(differences), 0.975),
        bootstrap95=bootstrap95ConfidenceInterval(
            differences,
            resamples=bootstrapResamples,
            seed=seed,
        ),
        effectSize=pairedEffectSize(baseline, intervention),
        signConsistency=signConsistency,
        positiveTailProbability=sum(value > 0 for value in differences) / len(differences),
        negativeTailProbability=sum(value < 0 for value in differences) / len(differences),
        differences=differences,
    )


def evaluateNegativeControl(
    controlName: str,
    baseline: Sequence[float],
    control: Sequence[float],
    *,
    tolerance: float,
    bootstrapResamples: int = 5_000,
    seed: int = 0,
) -> NegativeControlResult:
    if not controlName:
        raise ValueError("controlName must not be empty")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and non-negative")
    analysis = analyzePairedExperiment(
        baseline,
        control,
        bootstrapResamples=bootstrapResamples,
        seed=seed,
    )
    withinTolerance = abs(analysis.meanDifference) <= tolerance
    includesZero = analysis.bootstrap95.containsZero
    passed = withinTolerance and includesZero
    reasons = []
    if not withinTolerance:
        reasons.append("mean effect exceeds preregistered tolerance")
    if not includesZero:
        reasons.append("bootstrap interval excludes zero")
    return NegativeControlResult(
        controlName=controlName,
        tolerance=tolerance,
        analysis=analysis,
        passed=passed,
        reason="passed" if passed else "; ".join(reasons),
    )


def evaluateKnockout(
    knockoutName: str,
    baseline: Sequence[float],
    fullMechanism: Sequence[float],
    knockout: Sequence[float],
    *,
    minimumAttenuationFraction: float = 0.25,
    bootstrapResamples: int = 5_000,
    seed: int = 0,
) -> KnockoutResult:
    """比较完整机制和局部 knockout 的 matched-seed 效应衰减。"""

    if not knockoutName:
        raise ValueError("knockoutName must not be empty")
    if not 0.0 <= minimumAttenuationFraction <= 1.0:
        raise ValueError("minimumAttenuationFraction must be between 0 and 1")
    fullDifferences = pairedDifferences(baseline, fullMechanism)
    knockoutDifferences = pairedDifferences(baseline, knockout)
    if len(fullDifferences) != len(knockoutDifferences):
        raise ValueError("fullMechanism and knockout must use the same matched seeds")
    fullEffect = statistics.fmean(fullDifferences)
    knockoutEffect = statistics.fmean(knockoutDifferences)
    attenuationFraction = (
        (abs(fullEffect) - abs(knockoutEffect)) / abs(fullEffect) if fullEffect != 0 else None
    )
    expectedSign = 1.0 if fullEffect >= 0 else -1.0
    attenuationBySeed = tuple(
        (fullValue - knockoutValue) * expectedSign
        for fullValue, knockoutValue in zip(
            fullDifferences,
            knockoutDifferences,
            strict=True,
        )
    )
    interval = bootstrap95ConfidenceInterval(
        attenuationBySeed,
        resamples=bootstrapResamples,
        seed=seed,
    )
    mechanismSupported = (
        attenuationFraction is not None
        and attenuationFraction >= minimumAttenuationFraction
        and interval.lower > 0
    )
    return KnockoutResult(
        knockoutName=knockoutName,
        fullEffect=fullEffect,
        knockoutEffect=knockoutEffect,
        attenuationFraction=attenuationFraction,
        attenuationInterval=interval,
        minimumAttenuationFraction=minimumAttenuationFraction,
        mechanismSupported=mechanismSupported,
    )


def _validatedValues(
    values: Sequence[float],
    name: str,
    *,
    minimumSize: int,
) -> tuple[float, ...]:
    resolved = tuple(float(value) for value in values)
    if len(resolved) < minimumSize:
        raise ValueError(f"{name} must contain at least {minimumSize} values")
    if any(not math.isfinite(value) for value in resolved):
        raise ValueError(f"{name} must contain only finite values")
    return resolved


def _quantile(sortedValues: Sequence[float], probability: float) -> float:
    if not sortedValues:
        raise ValueError("cannot calculate a quantile from an empty sample")
    position = (len(sortedValues) - 1) * probability
    lowerIndex = math.floor(position)
    upperIndex = math.ceil(position)
    if lowerIndex == upperIndex:
        return float(sortedValues[lowerIndex])
    fraction = position - lowerIndex
    return float(sortedValues[lowerIndex] * (1 - fraction) + sortedValues[upperIndex] * fraction)


def _averageRanks(values: Sequence[float]) -> tuple[float, ...]:
    orderedIndices = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(orderedIndices):
        end = cursor + 1
        while end < len(orderedIndices) and (
            values[orderedIndices[end]] == values[orderedIndices[cursor]]
        ):
            end += 1
        averageRank = (cursor + 1 + end) / 2
        for orderedIndex in orderedIndices[cursor:end]:
            ranks[orderedIndex] = averageRank
        cursor = end
    return tuple(ranks)


def _pearsonCorrelation(left: Sequence[float], right: Sequence[float]) -> float:
    leftMean = statistics.fmean(left)
    rightMean = statistics.fmean(right)
    numerator = sum(
        (leftValue - leftMean) * (rightValue - rightMean)
        for leftValue, rightValue in zip(left, right, strict=True)
    )
    leftSquares = sum((value - leftMean) ** 2 for value in left)
    rightSquares = sum((value - rightMean) ** 2 for value in right)
    denominator = math.sqrt(leftSquares * rightSquares)
    return numerator / denominator if denominator else 0.0
