import { describe, expect, it } from 'vitest';
import {
  buildHistogram,
  normalizeCases,
  normalizeCognitionEvalSummary,
  normalizeCognitionEvaluationRun,
  normalizeEventPack,
  normalizeExperiment,
  normalizeGovernanceInventory,
  normalizeRedTeamRegistry,
  normalizeReleaseGate,
  normalizeResults,
  normalizeSavedScenario,
  normalizeScenarioDiff,
  normalizeStudyDesignPreview,
  normalizeStudyPresetCatalog,
  normalizeStudyRun,
  normalizeStudyRuns,
  normalizeSystemMetrics,
  normalizeValidation,
  normalizeValidationLadder,
} from './normalize';

describe('API normalizers', () => {
  it('preserves Study validity boundaries, resource limits, and immutable run metadata', () => {
    const catalog = normalizeStudyPresetCatalog({
      schemaVersion: '1.0.0',
      historicalValidityEstablished: false,
      validityBoundary: 'Model-internal templates only.',
      requiredNegativeControlCount: 8,
      requiredAblationCount: 10,
      supportedOutcomes: [{ outcomeId: 'max-spread-bps', unit: 'basis-points' }],
      supportedFactors: [{ parameterPath: 'intervention.value', unit: 'multiplier', minimum: 0.05, maximum: 4 }],
      items: [{
        presetId: 'spacex-s1-index-demand-liquidity',
        eventPackId: 'spacex-nasdaq100-2026-v1',
        title: 'SpaceX S1',
        titleZh: 'SpaceX S1',
        question: 'How does modeled liquidity change?',
        questionZh: '模型流动性如何变化？',
        recommendedInterventionParameter: 'marketMakerCapacity',
        factorPaths: ['intervention.value'],
        primaryOutcomeIds: ['max-spread-bps'],
      }],
    });
    expect(catalog).toMatchObject({
      historicalValidityEstablished: false,
      requiredNegativeControlCount: 8,
      requiredAblationCount: 10,
    });

    const preview = normalizeStudyDesignPreview({
      designKind: 'FULL_FACTORIAL',
      designCellCount: 3,
      requiredNegativeControlCount: 8,
      requiredAblationCount: 10,
      totalExecutionCells: 22,
      matchedSeedCount: 2,
      expectedRunCount: 44,
      estimatedWorkUnits: 18_480,
      maximumRunCount: 96,
      maximumWorkUnits: 150_000,
      withinResourceLimits: true,
      historicalValidityEstablished: false,
      cells: [{
        cellId: 'full-factorial-000',
        designKind: 'FULL_FACTORIAL',
        designIndex: 0,
        settings: [{
          path: 'intervention.value',
          value: 0.5,
          unit: 'multiplier',
          rationale: 'Bounded factor.',
          evidenceBasis: 'ASSUMPTION',
        }],
      }],
    });
    expect(preview).toMatchObject({ expectedRunCount: 44, estimatedWorkUnits: 18_480, withinResourceLimits: true });

    const run = normalizeStudyRun({
      runId: 'study-run-123',
      eventPackId: 'spacex-nasdaq100-2026-v1',
      studyId: 'spacex-study-v1',
      status: 'COMPLETED',
      specHash: 'sha256:spec',
      resultHash: 'sha256:stored',
      historicalValidityEstablished: false,
      createdAt: '2026-07-15T00:00:00Z',
      result: {
        schemaVersion: '1.0.0',
        runId: 'study-run-123',
        studyId: 'spacex-study-v1',
        status: 'COMPLETED',
        eventPackId: 'spacex-nasdaq100-2026-v1',
        historicalValidityEstablished: false,
        validityBoundary: 'No historical validity.',
        resourceBudget: {
          totalExecutionCells: 22,
          matchedSeedCount: 2,
          expectedRunCount: 44,
          estimatedWorkUnits: 18_480,
          maximumRunCount: 96,
          maximumWorkUnits: 150_000,
        },
        executionProtocol: {
          runner: 'runner-v1',
          marketKernel: 'DETERMINISTIC',
          cognitionMode: 'FROZEN_EVIDENCE_BOUND_COGNITIVE_TAPE_NOT_LIVE_LLM',
          matchedSeeds: true,
          requiredNegativeControlsIncluded: 8,
          requiredAblationsIncluded: 10,
          proxyAblationsAcknowledged: true,
          mechanismSemantics: [{ kind: 'NO_SOCIAL', status: 'BOUNDED_EXECUTABLE_PROXY', boundary: 'Nearest executable proxy.' }],
        },
        preregistration: {},
        result: {
          studyId: 'spacex-study-v1',
          cells: [],
          cellOutcomeAnalyses: [],
          holmFamilies: [],
          negativeControls: [],
          sensitivity: [],
          audit: {
            specHash: 'sha256:spec',
            resultHash: 'sha256:core',
            runnerName: 'runner-v1',
            expectedRunCount: 44,
            completedRunCount: 44,
            commonRandomSeedScheduleVerified: true,
            historicalValidityEstablished: false,
            validityBoundary: 'Model-internal only.',
          },
        },
      },
    });
    expect(run.result?.executionProtocol).toMatchObject({
      cognitionMode: 'FROZEN_EVIDENCE_BOUND_COGNITIVE_TAPE_NOT_LIVE_LLM',
      requiredAblationsIncluded: 10,
    });
    expect(normalizeStudyRuns({ items: [{ ...run, result: undefined }] })).toHaveLength(1);
  });

  it('preserves bilingual case and Event Pack fields from the backend schema', () => {
    const cases = normalizeCases([{
      id: 'synthetic-case',
      eventPackId: 'synthetic-pack-v1',
      title: 'Synthetic Case',
      titleZh: '合成案例',
      summary: 'Research fixture',
      summaryZh: '研究测试数据',
      synthetic: true,
    }]);
    expect(cases[0]).toMatchObject({
      id: 'synthetic-case',
      name: 'Synthetic Case',
      nameZh: '合成案例',
      isSynthetic: true,
    });

    const pack = normalizeEventPack({
      id: 'synthetic-pack-v1',
      caseId: 'synthetic-case',
      title: 'Synthetic Pack',
      titleZh: '合成事件包',
      summary: 'Bounded fixture',
      summaryZh: '有边界的测试数据',
      asOf: '2026-07-07T13:30:00Z',
      status: 'DRAFT',
      extraction: {
        mode: 'ZHIPU_STRUCTURED_OUTPUT',
        contentSecurity: {
          schemaVersion: '1.0.0',
          decision: 'REVIEW',
          acknowledged: true,
          sourceCount: 1,
          findingCount: 1,
          findingsTruncated: false,
          rawContentRetained: false,
          findings: [{
            sourceId: 'source-1',
            code: 'CONTACT_EMAIL',
            severity: 'MEDIUM',
            field: 'rawText',
            offset: 24,
          }],
          sources: [{
            sourceId: 'source-1',
            decision: 'REVIEW',
            sourceReviewLabel: 'HOST_NOT_ALLOWLISTED',
            findingCount: 1,
          }],
        },
      },
      synthetic: true,
      syntheticLabel: 'Real event facts with synthetic market assumptions',
      syntheticLabelZh: '真实事件事实与合成市场假设',
      sources: [{
        sourceId: 'source-1',
        sourceType: 'SYNTHETIC_RESEARCH_FIXTURE',
        title: 'Scenario note',
        titleZh: '场景说明',
        publishedAt: '2026-07-07T13:00:00Z',
        knownAt: '2026-07-07T13:05:00Z',
        license: 'Research fixture only',
        exportAllowed: false,
        contentHash: 'sha256:test',
      }],
      claims: [{
        claimId: 'claim-1',
        text: 'Candidate claim',
        textZh: '候选主张',
        sourceIds: ['source-1'],
        reviewStatus: 'AI_PROPOSED',
        isRequired: true,
      }],
      limitations: [{
        text: 'Market responses are synthetic.',
        textZh: '市场反应为合成结果。',
      }],
      defaultExperiment: {
        intervention: {
          parameter: 'marketMakerCapacity',
          baselineValue: 1,
          interventionValue: 0.45,
        },
        seedCount: 10,
        populationSize: 56,
        steps: 120,
      },
    });
    expect(pack.claims[0]).toMatchObject({
      id: 'claim-1',
      status: 'AI_PROPOSED',
      sourceIds: ['source-1'],
      textZh: '候选主张',
    });
    expect(pack.defaultExperiment).toMatchObject({
      eventPackId: 'synthetic-pack-v1',
      intervention: { parameter: 'marketMakerCapacity', interventionValue: 0.45 },
      populationSize: 56,
    });
    expect(pack).toMatchObject({
      extractionMode: 'ZHIPU_STRUCTURED_OUTPUT',
      contentSecurity: {
        decision: 'REVIEW',
        acknowledged: true,
        findingCount: 1,
        rawContentRetained: false,
      },
      isSynthetic: true,
      syntheticLabelZh: '真实事件事实与合成市场假设',
      limitationsZh: ['市场反应为合成结果。'],
    });
    expect(pack.sources[0]).toMatchObject({
      publishedAt: '2026-07-07T13:00:00Z',
      knownAt: '2026-07-07T13:05:00Z',
      exportAllowed: false,
    });
  });

  it('reads the nested experiment request and queue progress', () => {
    const experiment = normalizeExperiment({
      id: 'exp-test',
      status: 'AGGREGATING',
      request: {
        eventPackId: 'synthetic-pack-v1',
        question: 'How does lower capacity change stress?',
        intervention: {
          parameter: 'marketMakerCapacity',
          baselineValue: 1,
          interventionValue: 0.45,
        },
        seedCount: 10,
        populationSize: 56,
        steps: 120,
      },
      progress: 0.94,
      completedPairs: 10,
      totalPairs: 10,
      createdAt: '2026-07-15T00:00:00Z',
      runtime: {
        phase: 'INTERVENTION',
        pairIndex: 10,
        currentSeed: 12_345,
        resumedFromCheckpoint: true,
        checkpointPairs: 9,
        baseline: {
          step: 119,
          completedSteps: 120,
          totalSteps: 120,
          price: 134.25,
          spreadBps: 18.5,
          depth: 420,
          volume: 31,
          marketState: 'CONTINUOUS',
        },
        intervention: {
          step: 52,
          completedSteps: 53,
          totalSteps: 120,
          price: 131.75,
          spreadBps: 42.25,
          depth: 180,
          volume: 19,
          marketState: 'HALTED',
        },
        logs: [{
          timestamp: '2026-07-15T00:01:00Z',
          level: 'INFO',
          message: 'Intervention path is running.',
          seed: 12_345,
        }],
      },
    });
    expect(experiment.status).toBe('AGGREGATING');
    expect(experiment.progress).toBe(94);
    expect(experiment.eventPackId).toBe('synthetic-pack-v1');
    expect(experiment.intervention?.parameter).toBe('marketMakerCapacity');
    expect(experiment.scenario?.populationSize).toBe(56);
    expect(experiment.currentSeed).toBe(12_345);
    expect(experiment.liveState).toMatchObject({
      phase: 'INTERVENTION',
      checkpointPairs: 9,
      resumedFromCheckpoint: true,
      baseline: { price: 134.25, completedSteps: 120 },
      intervention: { marketState: 'HALTED', spreadBps: 42.25 },
    });
    expect(experiment.logs).toEqual([
      expect.objectContaining({ message: 'Intervention path is running.', seed: 12_345 }),
    ]);
  });

  it('preserves invalidation state without exposing a result as usable research', () => {
    const experiment = normalizeExperiment({
      id: 'exp-invalidated',
      status: 'INVALIDATED',
      request: {
        eventPackId: 'synthetic-pack-v1',
        intervention: {
          parameter: 'marketMakerCapacity',
          baselineValue: 1,
          interventionValue: 0.45,
        },
        seedCount: 10,
        populationSize: 56,
        steps: 120,
      },
      invalidatedAt: '2026-07-15T04:00:00Z',
      invalidationReasonCode: 'MODEL_ISSUE',
      invalidationReason: 'A model version mismatch was identified.',
      resultsAvailable: false,
      resultsPreserved: true,
      validForResearchUse: false,
    });

    expect(experiment).toMatchObject({
      status: 'INVALIDATED',
      invalidationReasonCode: 'MODEL_ISSUE',
      resultsAvailable: false,
      resultsPreserved: true,
      validForResearchUse: false,
    });
  });

  it('converts validation errors and estimated runs without inventing checks', () => {
    const validation = normalizeValidation({
      valid: false,
      errors: [{ code: 'EVENT_PACK_NOT_FROZEN', message: 'Freeze the pack.' }],
      warnings: [{ code: 'SMALL_SEED_COUNT', message: 'Wide interval.' }],
      estimatedRuns: 20,
    });
    expect(validation.valid).toBe(false);
    expect(validation.estimatedRuns).toBe(20);
    expect(validation.checks).toEqual([
      expect.objectContaining({ id: 'EVENT_PACK_NOT_FROZEN', passed: false }),
      expect.objectContaining({ id: 'SMALL_SEED_COUNT', passed: true }),
    ]);
  });

  it('uses authoritative backend checks and preserves the interpretation boundary', () => {
    const validation = normalizeValidation({
      valid: true,
      checks: [
        { code: 'EVENT_PACK_FROZEN', status: 'PASS', message: 'Frozen snapshot verified.' },
        { code: 'LLM_BUDGET_CLOSE_TO_CAP', status: 'WARN', message: 'Review the configured cap.' },
      ],
      estimatedLlmCalls: 40,
      llmCostCapUsd: 2.5,
      interpretationBoundary: 'Scenario analysis, not a forecast.',
    });
    expect(validation.checks).toEqual([
      expect.objectContaining({ id: 'EVENT_PACK_FROZEN', passed: true, severity: 'info' }),
      expect.objectContaining({ id: 'LLM_BUDGET_CLOSE_TO_CAP', passed: true, severity: 'warning' }),
    ]);
    expect(validation.estimatedLlmCalls).toBe(40);
    expect(validation.llmCostCapUsd).toBe(2.5);
    expect(validation.interpretationBoundary).toBe('Scenario analysis, not a forecast.');
  });

  it('converts aggregate result objects into chart arrays and metric rows', () => {
    const summary = {
      baseline: { median: 12, interval95: { lower: 10, upper: 14 } },
      intervention: { median: 20, interval95: { lower: 18, upper: 22 } },
      delta: {
        median: 8,
        interval95: { lower: 6, upper: 10 },
        directionConsistencyRate: 1,
        signConsistency: 1,
        bootstrap95: { lower: 5.5, upper: 10.5, containsZero: false },
        effectSize: { cohensDz: 2.1, matchedRankBiserial: 1, standardDeviationDifference: 0.3 },
        positiveTailProbability: 1,
        negativeTailProbability: 0,
        validN: 2,
      },
    };
    const results = normalizeResults({
      experimentId: 'exp-test',
      scenarioDiff: {
        parameter: 'marketMakerCapacity',
        baselineValue: 1,
        interventionValue: 0.45,
      },
      pairedRuns: [
        { seed: 100, baseline: { maxSpreadBps: 10 }, intervention: { maxSpreadBps: 18 }, delta: { maxSpreadBps: 8 } },
        { seed: 101, baseline: { maxSpreadBps: 14 }, intervention: { maxSpreadBps: 22 }, delta: { maxSpreadBps: 8 } },
      ],
      metricSummaries: { maxSpreadBps: summary },
      primaryOutcome: 'maxSpreadBps',
      medianPaths: {
        step: [0, 1],
        baseline: { price: [100, 99], spreadBps: [10, 12], depth: [300, 280] },
        intervention: { price: [100, 97], spreadBps: [12, 20], depth: [280, 210] },
      },
      agentFlows: {
        MARKET_MAKER: {
          baseline: { netVolume: 4 },
          intervention: { netVolume: -8 },
        },
      },
      agentPnl: {
        MARKET_MAKER: {
          equityChangeCents: {
            baseline: { median: 120 },
            intervention: { median: -80 },
            delta: { median: -200, validN: 2, directionConsistencyRate: 1 },
          },
        },
      },
      traces: [{
        traceId: 'trace-1',
        eventType: 'RISK_CHECK',
        step: 11,
        summary: 'Risk control checked the order.',
        summaryZh: '风控检查了订单。',
        payload: { agentId: 'agent-1', orderId: 'order-1' },
      }],
      limitations: [{ code: 'SYNTHETIC', text: 'Synthetic only.', textZh: '仅为合成数据。' }],
      cognition: {
        requestedMode: 'HYBRID_LLM',
        resolvedMode: 'HYBRID_LLM',
        provider: 'zhipu',
        requestedModel: 'glm-5',
        resolvedModel: 'glm-5',
        calls: 2,
        totalTokens: 520,
        cacheHits: 1,
        fallbackCount: 0,
        plannedCalls: 4,
        attemptedCalls: 2,
        decisionScheduleMode: 'POINT_IN_TIME_ROUNDS',
        promptVersion: 'cognition-v1',
        promptSchemaVersion: '1.0.0',
        decisions: [{
          agentId: 'agent-1',
          role: 'INSTITUTIONAL',
          requestId: 'request-1',
          cacheHit: true,
          representativeIndex: 0,
          decisionRound: 1,
          observationAt: '2026-07-07T13:15:00Z',
          activeFromStep: 30,
          decisionIntervalSteps: 30,
          evidenceCount: 1,
          socialPostCount: 2,
          memoryCount: 3,
          decision: {
            action_preference: 'REDUCE_RISK',
            direction: 'SELL',
            confidence: 0.72,
            uncertainty: 0.28,
            evidence: [{ evidence_id: 'claim-1' }],
            decision_summary: 'Reduce exposure under the approved evidence boundary.',
          },
        }],
      },
      robustness: {
        sensitivityStatus: 'PASSED',
        ablationStatus: 'NOT_EVALUATED',
        negativeControlStatus: 'PASSED',
        knockoutStatus: 'NOT_EVALUATED',
        notes: ['Synthetic mechanism validation only.'],
      },
      stoppingRule: {
        mode: 'TARGET_CI_HALF_WIDTH',
        triggered: true,
        reason: 'TARGET_CI_HALF_WIDTH_REACHED',
        primaryOutcome: 'maxSpreadBps',
        completedPairs: 10,
        observedCiHalfWidth: 1.2,
        targetCiHalfWidth: 1.5,
        bootstrapInterval95: { estimate: 8, lower: 6.8, upper: 9.2, confidenceLevel: 0.95, resamples: 5_000, seed: 17 },
      },
      narrativeReport: {
        schemaVersion: '1.0.0',
        headline: 'The intervention widened the simulated spread.',
        headlineZh: '干预扩大了模拟价差。',
        summary: 'Matched-seed scenario analysis only.',
        summaryZh: '仅为配对种子场景分析。',
        interpretationBoundary: 'SCENARIO_ANALYSIS_NOT_FORECAST',
        interpretationBoundaryZh: '场景分析，不是预测。',
        generatedBy: 'DETERMINISTIC_TEMPLATE',
      },
      analysisDiagnostics: {
        schemaVersion: '1.0.0',
        preregisteredPrimaryOutcome: 'maxSpreadBps',
        outcomeFamily: ['maxSpreadBps', 'minDepth'],
        negativeControl: { status: 'PASS', passed: true, tolerance: 0.1 },
        parameterRestorationKnockout: { status: 'PASS', mechanismSupported: true, attenuationFraction: 0.8 },
        localSensitivity: { status: 'PASS', design: 'LOCAL_GRID', indices: [{ parameter: 'marketMakerCapacity', spearmanCorrelation: -0.9, sampleSize: 5 }] },
        multipleComparison: { method: 'HOLM_BONFERRONI', alpha: 0.05, items: [{ hypothesisId: 'maxSpreadBps', rawPValue: 0.01, adjustedPValue: 0.02, rejected: true }] },
        interpretationBoundary: 'INTERNAL_MECHANISM_EVIDENCE_ONLY',
      },
      manifest: {
        generatedAt: '2026-07-15T00:00:00Z',
        validPairedSeeds: 2,
        engineVersion: 'engine-0.1.0',
        pythonVersion: '3.12.13',
        schemaVersion: '1.0.0',
      },
    });
    expect(results.metrics[0]).toMatchObject({
      id: 'maxSpreadBps',
      baseline: 12,
      intervention: 20,
      delta: 8,
      ciLow: 6,
      ciHigh: 10,
      n: 2,
      bootstrapContainsZero: false,
      cohensDz: 2.1,
    });
    expect(results.pairedSeeds).toHaveLength(2);
    expect(results.primaryMetricId).toBe('maxSpreadBps');
    expect(results.pairedSeries.maxSpreadBps).toHaveLength(2);
    expect(results.distribution.reduce((total, bin) => total + bin.baseline, 0)).toBe(2);
    expect(results.marketPaths[1]).toMatchObject({ baselinePrice: 99, interventionSpread: 20 });
    expect(results.agentFlows[0]).toMatchObject({ agentType: 'MARKET_MAKER', delta: -12 });
    expect(results.agentPnl[0]).toMatchObject({ agentType: 'MARKET_MAKER', deltaEquityChangeCents: -200, validN: 2 });
    expect(results.traces[0]).toMatchObject({ kind: 'RISK_CHECK', step: 11, summaryZh: '风控检查了订单。' });
    expect(results.limitationsZh).toEqual(['仅为合成数据。']);
    expect(results.modelVersions.engineVersion).toBe('engine-0.1.0');
    expect(results.cognition).toMatchObject({
      requestedMode: 'HYBRID_LLM',
      resolvedModel: 'glm-5',
      calls: 2,
      cacheHits: 1,
      fallbackCount: 0,
      plannedCalls: 4,
      attemptedCalls: 2,
    });
    expect(results.cognition?.decisions[0]).toMatchObject({
      agentId: 'agent-1',
      actionPreference: 'REDUCE_RISK',
      evidenceIds: ['claim-1'],
      decisionRound: 1,
      activeFromStep: 30,
      memoryCount: 3,
    });
    expect(results.robustness).toMatchObject({
      sensitivityStatus: 'PASSED',
      negativeControlStatus: 'PASSED',
    });
    expect(results.stoppingRule).toMatchObject({ triggered: true, completedPairs: 10, observedCiHalfWidth: 1.2 });
    expect(results.narrativeReport).toMatchObject({ generatedBy: 'DETERMINISTIC_TEMPLATE', headlineZh: '干预扩大了模拟价差。' });
    expect(results.analysisDiagnostics).toMatchObject({
      preregisteredPrimaryOutcome: 'maxSpreadBps',
      negativeControl: { passed: true },
      localSensitivity: { status: 'PASS' },
    });
  });

  it('normalizes saved scenarios, scenario diffs, executable evaluations, and runtime metrics', () => {
    const saved = normalizeSavedScenario({
      id: 'scenario-1',
      name: 'Capacity stress',
      frozen: true,
      contentHash: 'sha256:scenario',
      config: {
        eventPackId: 'pack-1',
        intervention: { parameter: 'marketMakerCapacity', baselineValue: 1, interventionValue: 0.5 },
        seedCount: 10,
        seedRoot: 20260707,
        populationSize: 56,
        steps: 120,
      },
    });
    expect(saved).toMatchObject({ id: 'scenario-1', frozen: true, config: { seedRoot: 20260707 } });

    const diff = normalizeScenarioDiff({
      changeCount: 1,
      changedPaths: ['intervention.interventionValue'],
      changes: [{ path: 'intervention.interventionValue', baseline: 1, intervention: 0.5 }],
      singleInterventionCompliant: true,
    });
    expect(diff).toMatchObject({ changeCount: 1, singleInterventionCompliant: true });

    const evaluation = normalizeCognitionEvaluationRun({
      mode: 'CODE_GRADER_SELF_TEST',
      evaluatedSystem: 'grader-wiring',
      suiteVersion: '1.0.0',
      result: {
        totalCases: 1,
        passedCases: 1,
        passRate: 1,
        results: [{ caseId: 'schema-valid', passed: true, score: 1, checks: [{ name: 'schema', passed: true, detail: 'Valid.' }] }],
      },
      modelRuns: [],
      interpretationBoundary: 'SELF_TEST_NOT_MODEL_QUALITY_EVIDENCE',
    });
    expect(evaluation).toMatchObject({ mode: 'CODE_GRADER_SELF_TEST', result: { passedCases: 1 } });

    const systemMetrics = normalizeSystemMetrics({
      service: 'eventshock-api',
      version: '0.1.0',
      runtime: {
        uptimeSeconds: 90,
        requestCount: 12,
        clientErrorCount: 1,
        serverErrorCount: 0,
        serverErrorRate: 0,
        latencyWindowSize: 12,
        latencyMs: { p50: 4, p95: 9, maximum: 12, mean: 5 },
        privacyBoundary: 'NO_PATH_BODY_SESSION_OR_CREDENTIAL_LABELS',
      },
      experiments: { workerConcurrency: 1, activeOrQueued: 0, maximumActiveOrQueued: 4, maximumExperimentsPerSession: 20 },
      storage: { database: 'ok', retainedExperiments: 3, maximumRetainedExperiments: 500 },
      cognition: { calls: 2, totalTokens: 400 },
      sloTargets: { availability: 0.99, apiP95Milliseconds: 800, status: 'TARGETS_NOT_PRODUCTION_EVIDENCE' },
    });
    expect(systemMetrics).toMatchObject({
      runtime: { requestCount: 12, latencyMs: { p95: 9 } },
      storage: { database: 'ok', retainedExperiments: 3 },
      cognition: { calls: 2, totalTokens: 400 },
    });
  });

  it('normalizes governance evidence without converting missing work into a pass', () => {
    const inventory = normalizeGovernanceInventory({
      inventoryHash: 'sha256:inventory',
      items: [{
        componentId: 'market-engine',
        name: 'Deterministic market engine',
        kind: 'SIMULATION_ENGINE',
        owner: 'Engineering',
        purpose: 'Convert bounded signals into orders and prices.',
        materiality: 'P0',
        version: '0.1.0',
        validation: [{ status: 'PENDING_HUMAN_EVIDENCE' }],
        limitations: ['Synthetic mechanisms only.'],
        approvalStatus: 'NOT_APPROVED',
        external: false,
      }],
    });
    expect(inventory.items[0]).toMatchObject({
      componentId: 'market-engine',
      validationStatuses: ['PENDING_HUMAN_EVIDENCE'],
      approvalStatus: 'NOT_APPROVED',
    });

    const redTeam = normalizeRedTeamRegistry({
      definitions: [{
        caseId: 'prompt-injection',
        title: 'Prompt injection',
        category: 'LLM_BOUNDARY',
        severity: 'P0',
        owner: 'AI Safety',
        automationCoverage: 'DEFINED_NOT_EXECUTED',
        requiresHumanEvidence: true,
      }],
      results: [{
        caseId: 'prompt-injection',
        category: 'LLM_BOUNDARY',
        status: 'NOT_RUN',
        score: 0,
        passed: false,
        detail: 'No execution evidence exists yet.',
      }],
      notice: 'NOT_RUN is not evidence of passing.',
    });
    expect(redTeam.results[0]).toMatchObject({ status: 'NOT_RUN', passed: false });

    const releaseGate = normalizeReleaseGate({
      report: {
        releaseId: 'release-candidate-1',
        decision: 'BLOCKED',
        canRelease: false,
        inventoryHash: 'sha256:inventory',
        humanEvidenceComplete: false,
        blockerGateIds: ['P0-EVIDENCE'],
        gateResults: [{
          gateId: 'P0-EVIDENCE',
          status: 'BLOCKED',
          detail: 'Human evidence is incomplete.',
          evidenceIds: [],
        }],
      },
      definitions: [{
        gateId: 'P0-EVIDENCE',
        title: 'P0 evidence gate',
        owner: 'Governance',
        criterion: 'All P0 evidence is complete.',
        failureEffect: 'Block release.',
      }],
      interpretationBoundary: 'Mechanism demonstration only.',
    });
    expect(releaseGate).toMatchObject({
      decision: 'BLOCKED',
      canRelease: false,
      humanEvidenceComplete: false,
      blockerGateIds: ['P0-EVIDENCE'],
    });

    const ladder = normalizeValidationLadder({
      highestAllowedClaim: 'MECHANISM_DEMONSTRATION',
      levels: [
        { level: 'L0', title: 'Unit checks', status: 'PASSED', boundary: 'Code behavior only.' },
        { level: 'L8', title: 'Decision validation', status: 'NOT_STARTED', boundary: 'No decision claim.' },
      ],
    });
    expect(ladder.highestAllowedClaim).toBe('MECHANISM_DEMONSTRATION');
    expect(ladder.levels[1]).toMatchObject({ level: 'L8', status: 'NOT_STARTED' });

    const evalSummary = normalizeCognitionEvalSummary({
      telemetry: { calls: 0, invalid_outputs: 0, total_tokens: 0 },
      evaluated_cases: 0,
      passed_cases: 0,
      pass_rate: 0,
    });
    expect(evalSummary).toMatchObject({ evaluatedCases: 0, passedCases: 0, passRate: 0 });
  });
});

describe('histogram builder', () => {
  it('keeps every real paired observation in the distribution counts', () => {
    const histogram = buildHistogram([
      { seed: 1, baseline: 1, intervention: 2, delta: 1 },
      { seed: 2, baseline: 2, intervention: 3, delta: 1 },
    ], 4);
    expect(histogram.reduce((total, bin) => total + bin.baseline, 0)).toBe(2);
    expect(histogram.reduce((total, bin) => total + bin.intervention, 0)).toBe(2);
  });
});
