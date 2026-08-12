import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Experiment } from './api/types';
import {
  guidedRunPresentation,
  readGuidedRunPlayback,
  startGuidedRunPlayback,
} from './guided-run-playback';

const completedExperiment: Experiment = {
  id: 'exp-guided-playback',
  eventPackId: 'pack-guided-playback',
  status: 'COMPLETED',
  progress: 100,
  validSeeds: 10,
  totalSeeds: 10,
  scenario: {
    eventPackId: 'pack-guided-playback',
    question: 'Does liquidity capacity change stress?',
    intervention: {
      parameter: 'marketMakerCapacity',
      baselineValue: 1,
      interventionValue: 0.65,
    },
    seedCount: 10,
    seedRoot: 2_026_070_700,
    populationSize: 56,
    steps: 120,
    network: {
      topology: 'WATTS_STROGATZ',
      averageDegree: 6,
      rewiringProbability: 0.12,
      echoChamberStrength: 0.35,
      correctionReach: 0.7,
    },
    market: {
      instrumentId: 'XAUUSD_SYNTH',
      benchmarkId: 'GOLD_SYNTHETIC',
      tickSize: 0.1,
      initialPrice: 3250,
      feeBps: 0.3,
      latencyMs: 25,
      openingAuction: true,
      volatilityHalt: true,
      priceCollarBps: 180,
    },
    llmPolicy: {
      mode: 'HYBRID_LLM',
      provider: 'zhipu',
      modelId: 'glm-5.2',
      representativeAgentCount: 2,
      decisionIntervalSteps: 60,
      callBudget: 4,
      maxCostUsd: 40,
      fallbackToRules: false,
    },
    primaryOutcome: 'maxSpreadBps',
    secondaryOutcomes: ['minDepth'],
    stoppingRule: { minimumPairs: 10, maximumPairs: 10 },
    acknowledgedScenarioNotForecast: true,
    acknowledgedSyntheticAssumptions: true,
  },
  liveState: {
    phase: 'COMPLETED',
    cognitionProgress: {
      status: 'COMPLETED',
      plannedCalls: 4,
      attemptedCalls: 4,
      completedCalls: 4,
      fallbackCount: 0,
      totalTokens: 3200,
    },
  },
  logs: [],
};

describe('guided run playback', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('persists the selected experiment without storing research results', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_000);
    startGuidedRunPlayback(completedExperiment.id, 62_000);
    expect(readGuidedRunPlayback()).toEqual({
      experimentId: completedExperiment.id,
      startedAtMs: 1_000,
      durationMs: 62_000,
    });
    expect(window.sessionStorage.getItem('eventshock-guided-run-playback-v1'))
      .not.toContain('results');
  });

  it('uses a concise default playback while preserving every presentation phase', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_000);
    expect(startGuidedRunPlayback(completedExperiment.id)).toMatchObject({
      durationMs: 22_000,
    });

    const playback = readGuidedRunPlayback()!;
    expect(guidedRunPresentation(playback, completedExperiment, 1_500, 'en').phase)
      .toBe('QUEUED');
    expect(guidedRunPresentation(playback, completedExperiment, 5_000, 'en').phase)
      .toBe('COGNITION');
    expect(guidedRunPresentation(playback, completedExperiment, 14_000, 'en').phase)
      .toBe('PAIRED_RUNS');
    expect(guidedRunPresentation(playback, completedExperiment, 21_000, 'en').phase)
      .toBe('AGGREGATING');
    expect(guidedRunPresentation(playback, completedExperiment, 24_000, 'en').phase)
      .toBe('COMPLETED');
  });

  it('shows queue, external cognition, paired runs, aggregation, and completion', () => {
    const playback = { experimentId: completedExperiment.id, startedAtMs: 1_000, durationMs: 62_000 };
    expect(guidedRunPresentation(playback, completedExperiment, 1_500, 'zh-CN').phase)
      .toBe('QUEUED');
    const cognition = guidedRunPresentation(playback, completedExperiment, 10_000, 'zh-CN');
    expect(cognition.phase).toBe('COGNITION');
    expect(cognition.cognitionProgress?.fallbackCount).toBe(0);
    expect(guidedRunPresentation(playback, completedExperiment, 35_000, 'en').phase)
      .toBe('PAIRED_RUNS');
    expect(guidedRunPresentation(playback, completedExperiment, 58_000, 'en').phase)
      .toBe('AGGREGATING');
    expect(guidedRunPresentation(playback, completedExperiment, 64_000, 'en')).toMatchObject({
      phase: 'COMPLETED',
      status: 'COMPLETED',
      progress: 100,
      validSeeds: 10,
    });
  });
});
