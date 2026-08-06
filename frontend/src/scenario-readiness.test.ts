import { describe, expect, it } from 'vitest';
import type { EventPack, ScenarioDraft } from './api/types';
import { getScenarioReadiness } from './scenario-readiness';

const FROZEN_PACK = {
  id: 'pack-ready',
  name: 'Ready pack',
  status: 'FROZEN',
  frozenAt: '2026-08-05T00:00:00Z',
  sources: [],
  claims: [],
} as unknown as EventPack;

const READY_SCENARIO: ScenarioDraft = {
  eventPackId: 'pack-ready',
  question: 'How does market-making capacity change the synthetic outcome?',
  questionInterventionParameter: 'marketMakerCapacity',
  questionReviewMethod: 'GENERATED_ALIGNED',
  intervention: { parameter: 'marketMakerCapacity', baselineValue: 1, interventionValue: 0.65 },
  seedCount: 10,
  seedRoot: 123,
  populationSize: 56,
  steps: 120,
  network: {
    topology: 'WATTS_STROGATZ', averageDegree: 6, rewiringProbability: 0.12,
    echoChamberStrength: 0.35, correctionReach: 0.7,
  },
  llmPolicy: {
    mode: 'RULE_ONLY', provider: 'zhipu', modelId: 'glm-5.2', representativeAgentCount: 8,
    decisionIntervalSteps: 12, callBudget: 24, maxCostUsd: 10, fallbackToRules: true,
  },
  stoppingRule: { minimumPairs: 10, maximumPairs: 10, targetCiHalfWidth: 25 },
};

describe('getScenarioReadiness', () => {
  it('未选择事件包时明确返回入口阻塞原因', () => {
    const result = getScenarioReadiness({
      eventPack: undefined,
      scenario: { ...READY_SCENARIO, eventPackId: '' },
      interventionBounds: { min: 0.1, max: 3 },
      llmModelReady: true,
      validationInProgress: false,
    });

    expect(result.ready).toBe(false);
    expect(result.blockers[0]).toMatchObject({
      code: 'EVENT_PACK_NOT_SELECTED',
      targetId: 'scenario-step-event',
      action: 'SELECT_CASE',
    });
  });

  it('只让已冻结且所有本地字段有效的草稿调用后端验证', () => {
    expect(getScenarioReadiness({
      eventPack: FROZEN_PACK,
      scenario: READY_SCENARIO,
      interventionBounds: { min: 0.1, max: 3 },
      llmModelReady: true,
      validationInProgress: false,
    })).toEqual({ ready: true, blockers: [], warnings: [] });
  });

  it('一次返回全部阻塞原因及可聚焦目标，而不是只禁用按钮', () => {
    const result = getScenarioReadiness({
      eventPack: { ...FROZEN_PACK, status: 'DRAFT', frozenAt: undefined },
      scenario: {
        ...READY_SCENARIO,
        questionInterventionParameter: undefined,
        intervention: { ...READY_SCENARIO.intervention, interventionValue: 1 },
        populationSize: 10,
        steps: 10,
        network: { ...READY_SCENARIO.network!, averageDegree: 12 },
        stoppingRule: { minimumPairs: 11, maximumPairs: 25 },
        llmPolicy: {
          ...READY_SCENARIO.llmPolicy!, mode: 'HYBRID_LLM', representativeAgentCount: 20,
          callBudget: 1, fallbackToRules: false,
        },
      },
      interventionBounds: { min: 0.1, max: 3 },
      llmModelReady: false,
      validationInProgress: true,
    });

    expect(result.ready).toBe(false);
    expect(result.blockers.map((item) => item.code)).toEqual([
      'EVENT_PACK_NOT_FROZEN',
      'INTERVENTION_VALUES_INVALID',
      'QUESTION_REVIEW_REQUIRED',
      'POPULATION_OUT_OF_RANGE',
      'SIMULATION_PLAN_INVALID',
      'NETWORK_DEGREE_INVALID',
      'STOPPING_RULE_INVALID',
      'LLM_CONFIGURATION_INVALID',
      'VALIDATION_IN_PROGRESS',
    ]);
    expect(result.blockers.find((item) => item.code === 'QUESTION_REVIEW_REQUIRED')?.targetId)
      .toBe('scenario-step-event');
  });
});
