import type { EventPack, ScenarioDraft } from './api/types';

export type ScenarioReadinessBlockerCode =
  | 'EVENT_PACK_NOT_SELECTED'
  | 'EVENT_PACK_NOT_FROZEN'
  | 'INTERVENTION_VALUES_INVALID'
  | 'QUESTION_REVIEW_REQUIRED'
  | 'POPULATION_OUT_OF_RANGE'
  | 'SIMULATION_PLAN_INVALID'
  | 'NETWORK_DEGREE_INVALID'
  | 'STOPPING_RULE_INVALID'
  | 'LLM_CONFIGURATION_INVALID'
  | 'VALIDATION_IN_PROGRESS';

export type ScenarioReadinessTargetId =
  | 'scenario-step-event'
  | 'scenario-step-market'
  | 'scenario-step-population'
  | 'scenario-step-network'
  | 'scenario-step-intervention'
  | 'scenario-step-review';

export interface ScenarioReadinessBlocker {
  code: ScenarioReadinessBlockerCode;
  targetId?: ScenarioReadinessTargetId;
  action: 'SELECT_CASE' | 'REVIEW_EVIDENCE' | 'FOCUS_FIELD' | 'WAIT';
}

export interface ScenarioReadinessResult {
  ready: boolean;
  blockers: ScenarioReadinessBlocker[];
  warnings: string[];
}

export interface ScenarioReadinessInput {
  eventPack?: EventPack;
  scenario: ScenarioDraft;
  interventionBounds: { min: number; max: number };
  llmModelReady: boolean;
  validationInProgress: boolean;
}

/**
 * 在调用后端验证前统一计算当前草稿是否具备“可提交验证”的最低条件。
 * 该函数只负责解释前端状态；后端仍是证据审核、冻结与运行权限的最终权威。
 */
export function getScenarioReadiness({
  eventPack,
  scenario,
  interventionBounds,
  llmModelReady,
  validationInProgress,
}: ScenarioReadinessInput): ScenarioReadinessResult {
  const blockers: ScenarioReadinessBlocker[] = [];
  const add = (blocker: ScenarioReadinessBlocker) => blockers.push(blocker);
  const isFrozen = eventPack?.status.toUpperCase() === 'FROZEN' || Boolean(eventPack?.frozenAt);

  if (!eventPack || !scenario.eventPackId) {
    add({
      code: 'EVENT_PACK_NOT_SELECTED',
      targetId: 'scenario-step-event',
      action: 'SELECT_CASE',
    });
  } else if (!isFrozen) {
    add({ code: 'EVENT_PACK_NOT_FROZEN', action: 'REVIEW_EVIDENCE' });
  }

  const { baselineValue, interventionValue } = scenario.intervention;
  if (
    !Number.isFinite(baselineValue)
    || !Number.isFinite(interventionValue)
    || baselineValue < interventionBounds.min
    || baselineValue > interventionBounds.max
    || interventionValue < interventionBounds.min
    || interventionValue > interventionBounds.max
    || baselineValue === interventionValue
  ) {
    add({
      code: 'INTERVENTION_VALUES_INVALID',
      targetId: 'scenario-step-intervention',
      action: 'FOCUS_FIELD',
    });
  }

  if (scenario.questionInterventionParameter !== scenario.intervention.parameter) {
    add({
      code: 'QUESTION_REVIEW_REQUIRED',
      targetId: 'scenario-step-event',
      action: 'FOCUS_FIELD',
    });
  }

  if (!Number.isInteger(scenario.populationSize) || scenario.populationSize < 14 || scenario.populationSize > 250) {
    add({
      code: 'POPULATION_OUT_OF_RANGE',
      targetId: 'scenario-step-population',
      action: 'FOCUS_FIELD',
    });
  }

  const seedRoot = scenario.seedRoot ?? 2_026_070_700;
  if (
    !Number.isInteger(scenario.steps)
    || scenario.steps < 30
    || scenario.steps > 300
    || !Number.isInteger(seedRoot)
    || seedRoot < 1
    || seedRoot > 2_147_483_000
  ) {
    add({
      code: 'SIMULATION_PLAN_INVALID',
      targetId: 'scenario-step-review',
      action: 'FOCUS_FIELD',
    });
  }

  const network = scenario.network;
  if (
    !network
    || !Number.isInteger(network.averageDegree)
    || network.averageDegree < 2
    || network.averageDegree >= scenario.populationSize
    || network.rewiringProbability < 0
    || network.rewiringProbability > 1
    || network.echoChamberStrength < 0
    || network.echoChamberStrength > 1
    || network.correctionReach < 0
    || network.correctionReach > 1
  ) {
    add({
      code: 'NETWORK_DEGREE_INVALID',
      targetId: 'scenario-step-network',
      action: 'FOCUS_FIELD',
    });
  }

  const stoppingRule = scenario.stoppingRule;
  if (
    !stoppingRule
    || !Number.isInteger(stoppingRule.minimumPairs)
    || stoppingRule.minimumPairs < 5
    || stoppingRule.minimumPairs > scenario.seedCount
    || stoppingRule.maximumPairs !== scenario.seedCount
    || (stoppingRule.targetCiHalfWidth !== undefined && stoppingRule.targetCiHalfWidth <= 0)
  ) {
    add({
      code: 'STOPPING_RULE_INVALID',
      targetId: 'scenario-step-review',
      action: 'FOCUS_FIELD',
    });
  }

  const llmPolicy = scenario.llmPolicy;
  if (llmPolicy?.mode === 'HYBRID_LLM' && (
    !Number.isInteger(llmPolicy.representativeAgentCount)
    || llmPolicy.representativeAgentCount < 1
    || llmPolicy.representativeAgentCount > scenario.populationSize
    || !Number.isInteger(llmPolicy.decisionIntervalSteps)
    || llmPolicy.decisionIntervalSteps < 1
    || llmPolicy.decisionIntervalSteps > 100
    || !Number.isInteger(llmPolicy.callBudget)
    || llmPolicy.callBudget < llmPolicy.representativeAgentCount
    || !Number.isFinite(llmPolicy.maxCostUsd)
    || llmPolicy.maxCostUsd < 0
    || (!llmModelReady && !llmPolicy.fallbackToRules)
  )) {
    add({
      code: 'LLM_CONFIGURATION_INVALID',
      targetId: 'scenario-step-population',
      action: 'FOCUS_FIELD',
    });
  }

  if (validationInProgress) {
    add({ code: 'VALIDATION_IN_PROGRESS', action: 'WAIT' });
  }

  return { ready: blockers.length === 0, blockers, warnings: [] };
}
