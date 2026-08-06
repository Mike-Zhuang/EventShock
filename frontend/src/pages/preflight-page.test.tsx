import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GuidedWorkflow } from '../api/types';
import {
  synchronizeGuidedHandoffOwner,
  writeGuidedReturnContext,
} from '../guided-handoff';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { PreflightPage } from './preflight-page';

vi.mock('../state/workflow-context', () => ({
  useWorkflow: vi.fn(),
  scenarioContentDigest: vi.fn(() => 'draft-current'),
}));

describe('PreflightPage 面向用户的枚举与停止规则', () => {
  const createAndStartExperiment = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    synchronizeGuidedHandoffOwner('preflight-guided-owner');
    vi.mocked(useWorkflow).mockReturnValue({
      eventPack: {
        id: 'pack-one',
        name: 'Generic event pack',
        status: 'FROZEN',
        pointInTime: '2026-07-22T10:00:00Z',
        limitations: [],
        limitationsZh: [],
        sources: [],
        claims: [],
      },
      scenario: {
        eventPackId: 'pack-one',
        question: 'How does one intervention change the synthetic path?',
        intervention: {
          parameter: 'marketMakerCapacity',
          baselineValue: 1,
          interventionValue: 0.5,
        },
        seedCount: 10,
        populationSize: 56,
        steps: 120,
        primaryOutcome: 'maxSpreadBps',
        secondaryOutcomes: [],
        stoppingRule: {
          minimumPairs: 10,
          maximumPairs: 10,
          targetCiHalfWidth: 1.5,
        },
        llmPolicy: { mode: 'RULE_ONLY' },
        acknowledgedScenarioNotForecast: true,
        acknowledgedSyntheticAssumptions: true,
      },
      validation: {
        valid: true,
        simulationRunnable: true,
        requestedCognitionRunnable: true,
        effectiveCognitionMode: 'RULE_ONLY',
        degradationReasons: [],
        requiresExplicitRuleFallbackConfirmation: false,
        checks: [{
          id: 'EVENT_PACK_FROZEN',
          label: 'EVENT_PACK_FROZEN',
          passed: true,
          detail: 'The Event Pack is frozen for this session.',
        }],
        estimatedLlmCalls: 0,
        estimatedRuns: 20,
        llmPricingStatus: 'NOT_APPLICABLE',
        interpretationBoundary: 'MECHANISM_DEMONSTRATION_NOT_FORECAST',
      },
      validationBinding: {
        kind: 'saved',
        scenarioId: 'scenario-one',
        scenarioName: 'Reviewed scenario',
        contentHash: 'a'.repeat(64),
        draftDigest: 'draft-current',
      },
      experimentsState: 'success',
      experimentsError: undefined,
      createAndStartExperiment,
    } as unknown as ReturnType<typeof useWorkflow>);
  });

  it('从引导进入时保留返回入口', () => {
    const navigate = vi.fn();
    writeGuidedReturnContext({
      schemaVersion: '1.0.0',
      id: 'guided-preflight-0001',
      stage: 'PREFLIGHT',
      status: 'ACTIVE',
      version: 8,
      language: 'en',
      draft: { searchQueries: [] },
      messages: [],
      createdAt: '2026-07-20T10:00:00Z',
      updatedAt: '2026-07-20T11:00:00Z',
    } satisfies GuidedWorkflow);

    render(<I18nProvider><PreflightPage navigate={navigate} /></I18nProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Return to AI guidance' }));

    expect(navigate).toHaveBeenCalledWith('guided');
  });

  it('translates internal modes and explains min equals max as a fixed run', () => {
    render(<I18nProvider><PreflightPage navigate={vi.fn()} /></I18nProvider>);

    expect(screen.getAllByText('Deterministic rules only (no external model call)'))
      .toHaveLength(2);
    expect(screen.getByText('Not applicable — no external model call')).toBeInTheDocument();
    expect(screen.getByText(
      'Mechanism demonstration and scenario comparison, not a real-world forecast',
    )).toBeInTheDocument();
    expect(screen.getByText(/Fixed at 10 matched pairs; the interval cannot stop the run early/))
      .toBeInTheDocument();
    expect(screen.getByText('Event Pack is frozen')).toBeInTheDocument();
    expect(screen.getByText(/bound to saved scenario Reviewed scenario \(scenario-one\)/))
      .toBeInTheDocument();
    expect(screen.queryByText(/SpaceX/)).not.toBeInTheDocument();
  });

  it('shows checkpoint capacity as a soft warning instead of blocking launch', () => {
    const current = vi.mocked(useWorkflow)();
    const validation = current.validation!;
    vi.mocked(useWorkflow).mockReturnValue({
      ...current,
      validation: {
        ...validation,
        checkpointCapacity: {
          estimatedStoredBytes: 24 * 1024 * 1024,
          warning: true,
          confidence: 'MEDIUM',
          sampleCount: 8,
        },
        checks: [
          ...validation.checks,
          {
            id: 'CHECKPOINT_CAPACITY',
            label: 'CHECKPOINT_CAPACITY',
            passed: true,
            severity: 'WARN',
            detail: 'Measured checkpoint telemetry predicts elevated retained storage usage.',
          },
        ],
      },
    } as ReturnType<typeof useWorkflow>);

    render(<I18nProvider><PreflightPage navigate={vi.fn()} /></I18nProvider>);

    expect(screen.getByText('24.0 MiB · MEDIUM')).toBeInTheDocument();
    expect(screen.getByText('Checkpoint storage capacity')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create and start experiment' }))
      .toBeInTheDocument();
  });

  it('hides raw validation enums behind human-readable labels', () => {
    const current = vi.mocked(useWorkflow)();
    const validation = current.validation!;
    vi.mocked(useWorkflow).mockReturnValue({
      ...current,
      validation: {
        ...validation,
        checks: [
          ...validation.checks,
          {
            id: 'LICENSE_REVIEW_REQUIRED_FOR_REDISTRIBUTION',
            label: 'LICENSE_REVIEW_REQUIRED_FOR_REDISTRIBUTION',
            passed: true,
            severity: 'warning',
            detail: 'Source availability is not redistribution permission.',
          },
        ],
      },
    } as ReturnType<typeof useWorkflow>);

    render(<I18nProvider><PreflightPage navigate={vi.fn()} /></I18nProvider>);

    expect(screen.getByText('Redistribution permission requires human review'))
      .toBeInTheDocument();
    expect(screen.queryByText('LICENSE_REVIEW_REQUIRED_FOR_REDISTRIBUTION'))
      .not.toBeInTheDocument();
  });

  it('keeps explicit human-retained question wording visible at the launch gate', () => {
    const current = vi.mocked(useWorkflow)();
    vi.mocked(useWorkflow).mockReturnValue({
      ...current,
      scenario: {
        ...current.scenario,
        questionReviewMethod: 'USER_CONFIRMED_UNCHANGED',
      },
    } as ReturnType<typeof useWorkflow>);

    render(<I18nProvider><PreflightPage navigate={vi.fn()} /></I18nProvider>);

    expect(screen.getByText('Research-question wording was retained')).toBeInTheDocument();
    expect(screen.getByText('User retained and explicitly confirmed the wording'))
      .toBeInTheDocument();
    expect(screen.getByText(/human judgment rather than proven semantic equivalence/))
      .toBeInTheDocument();
  });

  it('requires an explicit RULE_ONLY switch and starts with the effective scenario', async () => {
    const navigate = vi.fn();
    createAndStartExperiment.mockResolvedValue({ id: 'exp-rule-only' });
    const current = vi.mocked(useWorkflow)();
    vi.mocked(useWorkflow).mockReturnValue({
      ...current,
      scenario: {
        ...current.scenario,
        llmPolicy: {
          mode: 'HYBRID_LLM',
          provider: 'zhipu',
          modelId: 'glm-5.2',
          representativeAgentCount: 8,
          decisionIntervalSteps: 12,
          callBudget: 24,
          maxCostUsd: 3,
          fallbackToRules: true,
        },
      },
      validation: {
        ...current.validation,
        valid: false,
        simulationRunnable: true,
        requestedCognitionRunnable: false,
        effectiveCognitionMode: 'RULE_ONLY',
        degradationReasons: ['LLM_COST_CAP_INSUFFICIENT'],
        requiresExplicitRuleFallbackConfirmation: true,
      },
      createAndStartExperiment,
    } as ReturnType<typeof useWorkflow>);

    render(<I18nProvider><PreflightPage navigate={navigate} /></I18nProvider>);

    expect(screen.getByText('Explicit rule-only switch required')).toBeInTheDocument();
    expect(screen.getByText(/Hybrid LLM cannot run as configured/)).toBeInTheDocument();
    const startButton = screen.getByRole('button', { name: 'Switch to rule-only and start' });
    expect(startButton).toBeDisabled();

    screen.getAllByRole('checkbox').forEach((checkbox) => {
      if (!(checkbox as HTMLInputElement).checked) fireEvent.click(checkbox);
    });
    expect(startButton).toBeEnabled();
    fireEvent.click(startButton);

    await waitFor(() => {
      expect(createAndStartExperiment).toHaveBeenCalledWith(expect.objectContaining({
        llmPolicy: expect.objectContaining({ mode: 'RULE_ONLY' }),
      }));
      expect(navigate).toHaveBeenCalledWith('runs');
    });
  });

  it('blocks preflight when the validation binding does not match the current draft', () => {
    const navigate = vi.fn();
    const current = vi.mocked(useWorkflow)();
    vi.mocked(useWorkflow).mockReturnValue({
      ...current,
      validationBinding: {
        kind: 'unsaved-draft',
        draftDigest: 'draft-before-edit',
      },
    } as ReturnType<typeof useWorkflow>);

    render(<I18nProvider><PreflightPage navigate={navigate} /></I18nProvider>);

    expect(screen.getByRole('heading', {
      name: 'Validation no longer matches this draft',
    })).toBeInTheDocument();
    expect(screen.getByText(/scenario changed after validation/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create and start experiment' }))
      .not.toBeInTheDocument();
    expect(createAndStartExperiment).not.toHaveBeenCalled();
  });
});
