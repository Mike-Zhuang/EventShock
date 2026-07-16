"""Study 编排的不可变规格与强校验模型。

本模块只表达模型内部实验。它刻意不提供“历史有效”或“现实因果”状态，
因为运行一组模拟本身不能建立这两类主张。
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

ScalarValue = bool | int | float | str

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_PARAMETER_PATH_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class EvidenceBasis(StrEnum):
    EVIDENCE_BOUND = "EVIDENCE_BOUND"
    ASSUMPTION = "ASSUMPTION"
    SYNTHETIC = "SYNTHETIC"


class StudyClaimLevel(StrEnum):
    MECHANISM_DEMONSTRATION = "MECHANISM_DEMONSTRATION"
    MODEL_INTERNAL_SENSITIVITY = "MODEL_INTERNAL_SENSITIVITY"


class ExpectedDirection(StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    TWO_SIDED = "TWO_SIDED"


class DesignKind(StrEnum):
    FULL_FACTORIAL = "FULL_FACTORIAL"
    LATIN_HYPERCUBE = "LATIN_HYPERCUBE"


class StudyCellRole(StrEnum):
    BASELINE = "BASELINE"
    DESIGN = "DESIGN"
    NEGATIVE_CONTROL = "NEGATIVE_CONTROL"
    ABLATION = "ABLATION"


class NegativeControlKind(StrEnum):
    BASELINE_SELF = "BASELINE_SELF"
    IRRELEVANT_EVENT = "IRRELEVANT_EVENT"
    MISPLACED_EVENT_TIME = "MISPLACED_EVENT_TIME"
    LABEL_SWAP_TEXT_HELD = "LABEL_SWAP_TEXT_HELD"
    DISABLE_SOCIAL = "DISABLE_SOCIAL"
    DISABLE_LLM = "DISABLE_LLM"
    DISABLE_MM_INVENTORY_CONSTRAINT = "DISABLE_MM_INVENTORY_CONSTRAINT"
    NON_EVENT_DAY = "NON_EVENT_DAY"


class ControlExpectation(StrEnum):
    NULL_EFFECT = "NULL_EFFECT"
    MECHANISM_DIAGNOSTIC = "MECHANISM_DIAGNOSTIC"


class AblationKind(StrEnum):
    RULE_ONLY = "RULE_ONLY"
    LLM_REPRESENTATIVES_MIN_LIQUIDITY = "LLM_REPRESENTATIVES_MIN_LIQUIDITY"
    HYBRID = "HYBRID"
    NO_SOCIAL = "NO_SOCIAL"
    NO_MEMORY = "NO_MEMORY"
    NO_MM_INVENTORY_CONSTRAINT = "NO_MM_INVENTORY_CONSTRAINT"
    NO_PASSIVE_FUND = "NO_PASSIVE_FUND"
    FIXED_LLM_DECISIONS = "FIXED_LLM_DECISIONS"
    NO_RISK_OFF_FACTOR = "NO_RISK_OFF_FACTOR"
    NO_PRICE_IMPACT_SLIPPAGE = "NO_PRICE_IMPACT_SLIPPAGE"


REQUIRED_NEGATIVE_CONTROL_KINDS = frozenset(NegativeControlKind)
REQUIRED_ABLATION_KINDS = frozenset(AblationKind)
NULL_EFFECT_CONTROL_KINDS = frozenset(
    {
        NegativeControlKind.BASELINE_SELF,
        NegativeControlKind.IRRELEVANT_EVENT,
        NegativeControlKind.MISPLACED_EVENT_TIME,
        NegativeControlKind.LABEL_SWAP_TEXT_HELD,
        NegativeControlKind.NON_EVENT_DAY,
    }
)
MECHANISM_DIAGNOSTIC_CONTROL_KINDS = REQUIRED_NEGATIVE_CONTROL_KINDS - NULL_EFFECT_CONTROL_KINDS


@dataclass(frozen=True, slots=True)
class FrozenArtifact:
    artifactId: str
    sha256: str

    def __post_init__(self) -> None:
        _validateIdentifier(self.artifactId, "artifactId")
        if not isinstance(self.sha256, str) or not _SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("sha256 must use the form sha256:<64 lowercase hex chars>")


@dataclass(frozen=True, slots=True)
class OutcomeSpec:
    outcomeId: str
    unit: str
    familyId: str
    expectedDirection: ExpectedDirection
    rationale: str
    minimumEffectOfInterest: float | None = None

    def __post_init__(self) -> None:
        _validateIdentifier(self.outcomeId, "outcomeId")
        _validateIdentifier(self.familyId, "familyId")
        if not isinstance(self.expectedDirection, ExpectedDirection):
            raise ValueError("expectedDirection must be an ExpectedDirection")
        _validateText(self.unit, "unit")
        _validateText(self.rationale, "rationale")
        if self.minimumEffectOfInterest is not None:
            _validateFiniteNumber(
                self.minimumEffectOfInterest,
                "minimumEffectOfInterest",
            )
            if self.minimumEffectOfInterest < 0:
                raise ValueError("minimumEffectOfInterest must be non-negative")


@dataclass(frozen=True, slots=True)
class ParameterSetting:
    path: str
    value: ScalarValue
    unit: str
    rationale: str
    evidenceBasis: EvidenceBasis = EvidenceBasis.ASSUMPTION
    sourceReference: str | None = None

    def __post_init__(self) -> None:
        _validateParameterPath(self.path)
        if not isinstance(self.evidenceBasis, EvidenceBasis):
            raise ValueError("evidenceBasis must be an EvidenceBasis")
        _validateScalar(self.value, f"value for {self.path}")
        _validateText(self.unit, f"unit for {self.path}")
        _validateText(self.rationale, f"rationale for {self.path}")
        if isinstance(self.value, bool) and self.unit != "boolean":
            raise ValueError(f"boolean setting {self.path} must use unit 'boolean'")
        if self.evidenceBasis is EvidenceBasis.EVIDENCE_BOUND:
            _validateText(
                self.sourceReference,
                f"sourceReference for evidence-bound setting {self.path}",
            )
        elif self.sourceReference is not None:
            _validateText(self.sourceReference, f"sourceReference for {self.path}")


@dataclass(frozen=True, slots=True)
class DesignCell:
    cellId: str
    designKind: DesignKind
    settings: tuple[ParameterSetting, ...]
    designIndex: int

    def __post_init__(self) -> None:
        _validateIdentifier(self.cellId, "cellId")
        if not isinstance(self.designKind, DesignKind):
            raise ValueError("designKind must be a DesignKind")
        if (
            isinstance(self.designIndex, bool)
            or not isinstance(self.designIndex, int)
            or self.designIndex < 0
        ):
            raise ValueError("designIndex must be a non-negative integer")
        normalized = tuple(sorted(self.settings, key=lambda setting: setting.path))
        if not normalized:
            raise ValueError("a design cell must contain at least one parameter setting")
        _validateUniquePaths(normalized, f"design cell {self.cellId}")
        for setting in normalized:
            _validateFiniteNumber(setting.value, f"design value {setting.path}")
        object.__setattr__(self, "settings", normalized)


@dataclass(frozen=True, slots=True)
class OutcomeTolerance:
    outcomeId: str
    unit: str
    absoluteTolerance: float

    def __post_init__(self) -> None:
        _validateIdentifier(self.outcomeId, "outcomeId")
        _validateText(self.unit, "unit")
        _validateFiniteNumber(self.absoluteTolerance, "absoluteTolerance")
        if self.absoluteTolerance < 0:
            raise ValueError("absoluteTolerance must be non-negative")


@dataclass(frozen=True, slots=True)
class NegativeControlSpec:
    controlId: str
    kind: NegativeControlKind
    settings: tuple[ParameterSetting, ...]
    tolerances: tuple[OutcomeTolerance, ...]
    rationale: str
    expectation: ControlExpectation

    def __post_init__(self) -> None:
        _validateIdentifier(self.controlId, "controlId")
        if not isinstance(self.kind, NegativeControlKind):
            raise ValueError("kind must be a NegativeControlKind")
        if not isinstance(self.expectation, ControlExpectation):
            raise ValueError("expectation must be a ControlExpectation")
        _validateText(self.rationale, "rationale")
        normalizedSettings = tuple(sorted(self.settings, key=lambda setting: setting.path))
        _validateUniquePaths(normalizedSettings, f"negative control {self.controlId}")
        if self.kind is NegativeControlKind.BASELINE_SELF and normalizedSettings:
            raise ValueError("BASELINE_SELF must not alter any setting")
        if self.kind is not NegativeControlKind.BASELINE_SELF and not normalizedSettings:
            raise ValueError(f"negative control {self.kind} must declare an auditable setting")
        normalizedTolerances = tuple(
            sorted(self.tolerances, key=lambda tolerance: tolerance.outcomeId)
        )
        if len({item.outcomeId for item in normalizedTolerances}) != len(normalizedTolerances):
            raise ValueError("negative-control outcome tolerances must be unique")
        if self.expectation is ControlExpectation.NULL_EFFECT and not normalizedTolerances:
            raise ValueError("null-effect controls must declare outcome tolerances")
        if self.expectation is ControlExpectation.MECHANISM_DIAGNOSTIC and normalizedTolerances:
            raise ValueError("mechanism-diagnostic controls must not declare null tolerances")
        if self.kind in NULL_EFFECT_CONTROL_KINDS and (
            self.expectation is not ControlExpectation.NULL_EFFECT
        ):
            raise ValueError(f"negative control {self.kind} must expect a null effect")
        if self.kind in MECHANISM_DIAGNOSTIC_CONTROL_KINDS and (
            self.expectation is not ControlExpectation.MECHANISM_DIAGNOSTIC
        ):
            raise ValueError(f"negative control {self.kind} must be a mechanism diagnostic")
        object.__setattr__(self, "settings", normalizedSettings)
        object.__setattr__(self, "tolerances", normalizedTolerances)


@dataclass(frozen=True, slots=True)
class AblationSpec:
    ablationId: str
    kind: AblationKind
    settings: tuple[ParameterSetting, ...]
    question: str
    modelBoundary: str

    def __post_init__(self) -> None:
        _validateIdentifier(self.ablationId, "ablationId")
        if not isinstance(self.kind, AblationKind):
            raise ValueError("kind must be an AblationKind")
        _validateText(self.question, "question")
        _validateText(self.modelBoundary, "modelBoundary")
        normalized = tuple(sorted(self.settings, key=lambda setting: setting.path))
        if not normalized:
            raise ValueError("an ablation must declare at least one auditable setting")
        _validateUniquePaths(normalized, f"ablation {self.ablationId}")
        object.__setattr__(self, "settings", normalized)


@dataclass(frozen=True, slots=True)
class StudyPreregistration:
    studyId: str
    question: str
    claimLevel: StudyClaimLevel
    primaryOutcomes: tuple[OutcomeSpec, ...]
    secondaryOutcomes: tuple[OutcomeSpec, ...]
    exclusionRules: tuple[str, ...]
    supportCriterion: str
    contradictionCriterion: str
    inconclusiveCriterion: str
    knownLimitations: tuple[str, ...]
    frozenArtifacts: tuple[FrozenArtifact, ...]

    def __post_init__(self) -> None:
        _validateIdentifier(self.studyId, "studyId")
        _validateText(self.question, "question")
        if not isinstance(self.claimLevel, StudyClaimLevel):
            raise ValueError("claimLevel must be a StudyClaimLevel")
        if not 2 <= len(self.primaryOutcomes) <= 4:
            raise ValueError("primaryOutcomes must contain between 2 and 4 outcomes")
        if not self.secondaryOutcomes:
            raise ValueError("secondaryOutcomes must contain at least one outcome")
        allOutcomes = self.primaryOutcomes + self.secondaryOutcomes
        if len({outcome.outcomeId for outcome in allOutcomes}) != len(allOutcomes):
            raise ValueError("all preregistered outcome IDs must be unique")
        _validateTextItems(self.exclusionRules, "exclusionRules")
        _validateText(self.supportCriterion, "supportCriterion")
        _validateText(self.contradictionCriterion, "contradictionCriterion")
        _validateText(self.inconclusiveCriterion, "inconclusiveCriterion")
        _validateTextItems(self.knownLimitations, "knownLimitations")
        if not self.frozenArtifacts:
            raise ValueError("frozenArtifacts must contain at least one hashed artifact")
        if len({artifact.artifactId for artifact in self.frozenArtifacts}) != len(
            self.frozenArtifacts
        ):
            raise ValueError("frozen artifact IDs must be unique")

    @property
    def allOutcomes(self) -> tuple[OutcomeSpec, ...]:
        return self.primaryOutcomes + self.secondaryOutcomes


@dataclass(frozen=True, slots=True)
class StudySpec:
    preregistration: StudyPreregistration
    baselineSettings: tuple[ParameterSetting, ...]
    designCells: tuple[DesignCell, ...]
    negativeControls: tuple[NegativeControlSpec, ...]
    ablations: tuple[AblationSpec, ...]
    seeds: tuple[int, ...]
    alpha: float = 0.05
    bootstrapResamples: int = 1_000
    analysisSeed: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.preregistration, StudyPreregistration):
            raise ValueError("preregistration must be a StudyPreregistration")
        baselineSettings = tuple(sorted(self.baselineSettings, key=lambda item: item.path))
        _validateUniquePaths(baselineSettings, "baseline")
        if len(self.designCells) < 3:
            raise ValueError("designCells must contain at least 3 cells for rank sensitivity")
        designCells = tuple(sorted(self.designCells, key=lambda cell: cell.designIndex))
        if len({cell.cellId for cell in designCells}) != len(designCells):
            raise ValueError("design cell IDs must be unique")
        if len({cell.designIndex for cell in designCells}) != len(designCells):
            raise ValueError("design cell indices must be unique")
        self._validateDesignShape(designCells)

        negativeControls = tuple(sorted(self.negativeControls, key=lambda item: item.kind))
        _validateRequiredKinds(
            (control.kind for control in negativeControls),
            REQUIRED_NEGATIVE_CONTROL_KINDS,
            "negative controls",
        )
        self._validateControlTolerances(negativeControls)

        ablations = tuple(sorted(self.ablations, key=lambda item: item.kind))
        _validateRequiredKinds(
            (ablation.kind for ablation in ablations),
            REQUIRED_ABLATION_KINDS,
            "ablations",
        )
        if len(self.seeds) < 2:
            raise ValueError("seeds must contain at least 2 matched seeds")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in self.seeds
        ):
            raise ValueError("seeds must be non-negative integers")
        seeds = tuple(sorted(self.seeds))
        if len(set(seeds)) != len(seeds):
            raise ValueError("seeds must be unique")
        _validateFiniteNumber(self.alpha, "alpha")
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha must be between 0 and 1")
        if (
            isinstance(self.bootstrapResamples, bool)
            or not isinstance(self.bootstrapResamples, int)
            or self.bootstrapResamples < 100
        ):
            raise ValueError("bootstrapResamples must be an integer of at least 100")
        if (
            isinstance(self.analysisSeed, bool)
            or not isinstance(self.analysisSeed, int)
            or self.analysisSeed < 0
        ):
            raise ValueError("analysisSeed must be a non-negative integer")

        object.__setattr__(self, "baselineSettings", baselineSettings)
        object.__setattr__(self, "designCells", designCells)
        object.__setattr__(self, "negativeControls", negativeControls)
        object.__setattr__(self, "ablations", ablations)
        object.__setattr__(self, "seeds", seeds)

    def _validateDesignShape(self, designCells: tuple[DesignCell, ...]) -> None:
        referencePaths = tuple(setting.path for setting in designCells[0].settings)
        referenceMetadata = {
            setting.path: (setting.unit, setting.evidenceBasis, setting.sourceReference)
            for setting in designCells[0].settings
        }
        for cell in designCells[1:]:
            paths = tuple(setting.path for setting in cell.settings)
            if paths != referencePaths:
                raise ValueError("every design cell must vary the same parameter paths")
            metadata = {
                setting.path: (setting.unit, setting.evidenceBasis, setting.sourceReference)
                for setting in cell.settings
            }
            if metadata != referenceMetadata:
                raise ValueError("parameter unit and evidence metadata must match across cells")

    def _validateControlTolerances(
        self,
        controls: tuple[NegativeControlSpec, ...],
    ) -> None:
        expected = {
            outcome.outcomeId: outcome.unit for outcome in self.preregistration.primaryOutcomes
        }
        for control in controls:
            actual = {item.outcomeId: item.unit for item in control.tolerances}
            if control.expectation is ControlExpectation.NULL_EFFECT and actual != expected:
                raise ValueError(
                    f"negative control {control.controlId} must define exact primary-outcome "
                    "tolerances with matching units"
                )
            if control.expectation is ControlExpectation.MECHANISM_DIAGNOSTIC and actual:
                raise ValueError(
                    f"mechanism-diagnostic control {control.controlId} cannot use null tolerances"
                )


def _validateRequiredKinds(
    values: Iterable[StrEnum],
    required: frozenset[StrEnum],
    label: str,
) -> None:
    resolved = tuple(values)
    if len(set(resolved)) != len(resolved):
        raise ValueError(f"{label} must not contain duplicate kinds")
    actual = frozenset(resolved)
    if actual != required:
        missing = sorted(item.value for item in required - actual)
        extra = sorted(item.value for item in actual - required)
        raise ValueError(f"{label} must match the required set; missing={missing}; extra={extra}")


def _validateIdentifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase stable identifier")


def _validateParameterPath(value: str) -> None:
    if not isinstance(value, str) or not _PARAMETER_PATH_PATTERN.fullmatch(value):
        raise ValueError("parameter paths must be lowercase dotted identifiers")


def _validateText(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{name} must not contain leading or trailing whitespace")


def _validateTextItems(values: tuple[str, ...], name: str) -> None:
    if not values:
        raise ValueError(f"{name} must contain at least one item")
    for index, value in enumerate(values):
        _validateText(value, f"{name}[{index}]")


def _validateScalar(value: ScalarValue, name: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        _validateFiniteNumber(value, name)
        return
    if isinstance(value, str) and value and value == value.strip():
        return
    raise ValueError(f"{name} must be a finite number, boolean, or non-empty string")


def _validateFiniteNumber(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")


def _validateUniquePaths(settings: tuple[ParameterSetting, ...], context: str) -> None:
    paths = [setting.path for setting in settings]
    if len(set(paths)) != len(paths):
        raise ValueError(f"{context} contains duplicate parameter paths")
