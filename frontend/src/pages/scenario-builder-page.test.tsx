import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type {
  GuidedWorkflow,
  LlmModelDescriptor,
  SavedScenario,
  ScenarioDraft,
  ScenarioValidation,
} from '../api/types';
import { I18nProvider } from '../i18n';
import {
  buildAlignedInterventionQuestions,
  findMechanismDisabledCheck,
  focusScenarioStep,
  getLlmModelAvailability,
  GuidedScenarioReplacementError,
  linkSavedScenarioToGuidedWorkflow,
  MechanismDisabledRecovery,
  ScenarioReadinessPanel,
  scenarioReadinessCopy,
  scenarioQuestionNeedsReview,
  scenariosHaveSameContent,
  SecondaryOutcomeOption,
} from './scenario-builder-page';

describe('次要结果指标布局', () => {
  it('复选框与完整文本保持为两列中的两个直接子元素', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container } = render(
      <SecondaryOutcomeOption
        id="maxDrawdownPct"
        label="最大回撤"
        checked={false}
        onChange={onChange}
      />,
    );

    const row = container.querySelector<HTMLLabelElement>('.native-check-row');
    expect(row).not.toBeNull();
    expect(row?.children).toHaveLength(2);
    expect(row?.querySelector('.native-check-row__label')).toHaveTextContent('最大回撤');
    expect(row?.querySelector('[aria-hidden="true"]')).not.toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: '最大回撤' }));
    expect(onChange).toHaveBeenCalledOnce();
  });

  it('分别识别价格未核验与输出上限未核验，避免把 K2.6 错报为费用闸门可用', () => {
    const readyModel: LlmModelDescriptor = {
      provider: 'zhipu', id: 'ready', name: 'Ready', contextTokens: 128_000,
      maxOutputTokens: 32_768, supportsThinking: true, supportsFunctionCalling: true,
      recommended: true, qualityTier: 'BALANCED', freeTier: false, legacy: false,
      pricingStatus: 'VERIFIED_UPPER_BOUND', billingCurrency: 'CNY',
    };
    const missingOutputLimit = { ...readyModel, id: 'kimi-k2.6', maxOutputTokens: undefined };
    const missingPrice = { ...readyModel, id: 'unpriced', pricingStatus: 'UNAVAILABLE_FAIL_CLOSED' as const };

    expect(getLlmModelAvailability(readyModel)).toBe('READY');
    expect(getLlmModelAvailability(missingOutputLimit)).toBe('OUTPUT_LIMIT_UNVERIFIED');
    expect(getLlmModelAvailability(missingPrice)).toBe('PRICE_UNVERIFIED');
    expect(getLlmModelAvailability(undefined)).toBe('MISSING');
  });
});

describe('情景验证修复与草稿版本语义', () => {
  it('在宽版主内容区一次展示全部阻塞项和修复入口', async () => {
    const user = userEvent.setup();
    const onReviewEvidence = vi.fn();
    const onFocusTarget = vi.fn();
    const { container } = render(
      <ScenarioReadinessPanel
        readiness={{
          ready: false,
          warnings: [],
          blockers: [
            { code: 'EVENT_PACK_NOT_FROZEN', action: 'REVIEW_EVIDENCE' },
            {
              code: 'QUESTION_REVIEW_REQUIRED',
              action: 'FOCUS_FIELD',
              targetId: 'scenario-step-event',
            },
          ],
        }}
        isZh={false}
        onSelectCase={vi.fn()}
        onReviewEvidence={onReviewEvidence}
        onFocusTarget={onFocusTarget}
      />,
    );

    expect(container.querySelector('.scenario-readiness--prominent')).not.toBeNull();
    expect(screen.getByRole('heading', { name: '2 item(s) need attention' }))
      .toBeInTheDocument();
    expect(screen.getByText('The Event Pack has not been reviewed and frozen.'))
      .toBeInTheDocument();
    expect(screen.getByText(/research question is not confirmed/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Continue evidence review' }));
    await user.click(screen.getByRole('button', { name: 'Review the research question' }));
    expect(onReviewEvidence).toHaveBeenCalledOnce();
    expect(onFocusTarget).toHaveBeenCalledWith('scenario-step-event');
  });

  it('为阻塞项提供完整的中英文用户文案', () => {
    const blocker = {
      code: 'EVENT_PACK_NOT_FROZEN' as const,
      action: 'REVIEW_EVIDENCE' as const,
    };
    expect(scenarioReadinessCopy(blocker, false)).toEqual({
      title: 'The Event Pack has not been reviewed and frozen.',
      action: 'Continue evidence review',
    });
    expect(scenarioReadinessCopy(blocker, true)).toEqual({
      title: 'Event Pack 尚未完成审核与冻结。',
      action: '继续审核证据',
    });
  });

  it('切换干预后要求重新确认研究问题，并生成与干预一致的双语问题', () => {
    const scenario: ScenarioDraft = {
      eventPackId: 'pack-one',
      question: 'How does lower market-making capacity affect the synthetic instrument?',
      questionZh: '降低做市能力会如何影响合成标的？',
      questionInterventionParameter: 'marketMakerCapacity',
      intervention: {
        parameter: 'marketMakerCapacity',
        baselineValue: 1,
        interventionValue: 0.45,
      },
      seedCount: 10,
      populationSize: 56,
      steps: 120,
    };

    expect(scenarioQuestionNeedsReview(scenario)).toBe(false);
    const staleScenario = {
      ...scenario,
      intervention: {
        parameter: 'socialAmplification' as const,
        baselineValue: 1,
        interventionValue: 1.6,
      },
    };
    expect(scenarioQuestionNeedsReview(staleScenario)).toBe(true);

    const aligned = buildAlignedInterventionQuestions('socialAmplification', 'SYNTH-BA');
    expect(aligned.question).toContain('social amplification');
    expect(aligned.question).toContain('SYNTH-BA');
    expect(aligned.questionZh).toContain('社交放大强度');
    expect(aligned.questionInterventionParameter).toBe('socialAmplification');
    expect(aligned.questionReviewMethod).toBe('GENERATED_ALIGNED');
    expect(scenarioQuestionNeedsReview({ ...staleScenario, ...aligned })).toBe(false);
  });

  it('步骤定位只滚动并聚焦目标，不污染当前 hash 路由', () => {
    window.history.replaceState(null, '', '#/scenario');
    const section = document.createElement('section');
    section.id = 'scenario-market-section';
    section.tabIndex = -1;
    const scrollIntoView = vi.fn();
    section.scrollIntoView = scrollIntoView;
    document.body.append(section);

    expect(focusScenarioStep(section.id)).toBe(true);
    expect(document.activeElement).toBe(section);
    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(window.location.hash).toBe('#/scenario');
    expect(focusScenarioStep('missing-scenario-section')).toBe(false);

    section.remove();
  });

  it('为机制禁用错误提供可直接执行的两个修复动作和折叠技术详情', async () => {
    const user = userEvent.setup();
    const onUseMarketMaker = vi.fn();
    const onReviewEvidence = vi.fn();
    render(
      <I18nProvider>
        <MechanismDisabledRecovery
          claimId="claim-clarification-review"
          onUseMarketMaker={onUseMarketMaker}
          onReviewEvidence={onReviewEvidence}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole('heading', {
      name: 'Clarification delay is unavailable for this Event Pack',
    })).toBeInTheDocument();
    expect(screen.getByText(/no approved clarification claim/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Use market-making capacity' }));
    await user.click(screen.getByRole('button', {
      name: 'Review evidence and add clarification claim',
    }));
    expect(onUseMarketMaker).toHaveBeenCalledOnce();
    expect(onReviewEvidence).toHaveBeenCalledOnce();

    const details = screen.getByText('Technical details').closest('details');
    expect(details).not.toHaveAttribute('open');
    await user.click(screen.getByText('Technical details'));
    expect(details).toHaveAttribute('open');
    expect(screen.getByText('claim-clarification-review')).toBeVisible();
    expect(screen.getByText('INTERVENTION_MECHANISM_DISABLED')).toBeVisible();
  });

  it('识别机制错误，并用完整规范化内容而非对象引用判断 dirty 状态', () => {
    const validation: ScenarioValidation = {
      valid: false,
      simulationRunnable: false,
      requestedCognitionRunnable: false,
      degradationReasons: [],
      requiresExplicitRuleFallbackConfirmation: false,
      checks: [{
        id: 'INTERVENTION_MECHANISM_DISABLED',
        label: 'INTERVENTION_MECHANISM_DISABLED',
        passed: false,
        severity: 'error',
      }],
    };
    expect(findMechanismDisabledCheck(validation)?.id)
      .toBe('INTERVENTION_MECHANISM_DISABLED');

    const saved: ScenarioDraft = {
      eventPackId: 'pack-one',
      intervention: {
        parameter: 'marketMakerCapacity',
        baselineValue: 1,
        interventionValue: 0.45,
      },
      seedCount: 10,
      populationSize: 56,
      steps: 120,
      secondaryOutcomes: ['maxDrawdownPct', 'recoverySteps'],
    };
    const reordered = {
      steps: 120,
      populationSize: 56,
      seedCount: 10 as const,
      secondaryOutcomes: ['maxDrawdownPct', 'recoverySteps'],
      intervention: {
        interventionValue: 0.45,
        baselineValue: 1,
        parameter: 'marketMakerCapacity' as const,
      },
      eventPackId: 'pack-one',
    };

    expect(scenariosHaveSameContent(saved, reordered)).toBe(true);
    expect(scenariosHaveSameContent(saved, { ...saved, steps: 121 })).toBe(false);
  });
});

describe('AI 引导情景交接', () => {
  it('只把服务器返回的真实情景 ID 关联到当前版本的引导工作流', async () => {
    const savedScenario: SavedScenario = {
      id: 'scenario-server-returned',
      name: 'Human-reviewed scenario',
      frozen: true,
      contentHash: 'a'.repeat(64),
      config: {
        eventPackId: 'event-pack-reviewed',
        intervention: {
          parameter: 'marketMakerCapacity',
          baselineValue: 1,
          interventionValue: 0.45,
        },
        seedCount: 10,
        populationSize: 56,
        steps: 120,
      },
    };
    const workflow: GuidedWorkflow = {
      schemaVersion: '1.0.0',
      id: 'guided-12345678',
      stage: 'SCENARIO_INTERVENTION',
      status: 'ACTIVE',
      version: 9,
      language: 'en',
      draft: {
        searchQueries: [],
        eventPackId: savedScenario.config.eventPackId,
      },
      messages: [],
      createdAt: '2026-07-22T10:00:00Z',
      updatedAt: '2026-07-22T10:05:00Z',
    };
    const workflowSpy = vi.spyOn(api, 'getGuidedWorkflow').mockResolvedValue(workflow);
    const linkSpy = vi.spyOn(api, 'linkGuidedWorkflowArtifacts').mockResolvedValue({
      ...workflow,
      version: 10,
      draft: { ...workflow.draft, scenarioId: savedScenario.id },
    });

    await linkSavedScenarioToGuidedWorkflow(workflow.id, savedScenario);

    expect(workflowSpy).toHaveBeenCalledWith(workflow.id);
    expect(linkSpy).toHaveBeenCalledWith(workflow.id, {
      expectedVersion: workflow.version,
      scenarioId: savedScenario.id,
    });
    workflowSpy.mockRestore();
    linkSpy.mockRestore();
  });

  it('只链接冻结情景，替换已链接情景的不可变判定交由带审计的后端强制', async () => {
    const baseConfig: SavedScenario['config'] = {
      eventPackId: 'event-pack-reviewed',
      intervention: {
        parameter: 'marketMakerCapacity',
        baselineValue: 1,
        interventionValue: 0.45,
      },
      seedCount: 10,
      populationSize: 56,
      steps: 120,
    };

    // 未冻结情景在任何服务器调用之前就被前端拒绝，避免把未冻结对象写进工作流。
    const unfrozenScenario: SavedScenario = {
      id: 'scenario-unfrozen',
      name: 'Not yet frozen',
      frozen: false,
      contentHash: '',
      config: baseConfig,
    };
    const workflowSpy = vi.spyOn(api, 'getGuidedWorkflow');
    const linkSpy = vi.spyOn(api, 'linkGuidedWorkflowArtifacts');
    await expect(linkSavedScenarioToGuidedWorkflow('guided-12345678', unfrozenScenario))
      .rejects.toBeInstanceOf(GuidedScenarioReplacementError);
    expect(workflowSpy).not.toHaveBeenCalled();
    expect(linkSpy).not.toHaveBeenCalled();

    // 工作流已链接同一情景时保持幂等，不重复调用后端、不重复写审计。
    const frozenScenario: SavedScenario = {
      id: 'scenario-frozen',
      name: 'Frozen scenario',
      frozen: true,
      contentHash: 'b'.repeat(64),
      config: baseConfig,
    };
    const alreadyLinkedSame = {
      schemaVersion: '1.0.0',
      id: 'guided-12345678',
      stage: 'SCENARIO_REVIEW',
      status: 'ACTIVE',
      version: 10,
      language: 'en',
      draft: {
        searchQueries: [],
        eventPackId: 'event-pack-reviewed',
        scenarioId: frozenScenario.id,
      },
      messages: [],
      createdAt: '2026-07-22T10:00:00Z',
      updatedAt: '2026-07-22T10:05:00Z',
    } satisfies GuidedWorkflow;
    workflowSpy.mockResolvedValue(alreadyLinkedSame);
    await linkSavedScenarioToGuidedWorkflow(alreadyLinkedSame.id, frozenScenario);
    expect(linkSpy).not.toHaveBeenCalled();

    // 替换一个仍存在的不同情景由后端按不可变规则拒绝；前端如实传播错误，绝不伪造成功。
    const differentFrozen: SavedScenario = {
      id: 'scenario-different',
      name: 'Different scenario',
      frozen: true,
      contentHash: 'c'.repeat(64),
      config: baseConfig,
    };
    const linksAnother = {
      ...alreadyLinkedSame,
      draft: { ...alreadyLinkedSame.draft, scenarioId: 'scenario-already-linked' },
    } satisfies GuidedWorkflow;
    workflowSpy.mockResolvedValue(linksAnother);
    linkSpy.mockRejectedValue(
      new Error('the linked scenario is immutable while it still exists'),
    );
    await expect(linkSavedScenarioToGuidedWorkflow(linksAnother.id, differentFrozen))
      .rejects.toThrow(/immutable while it still exists/);
    expect(linkSpy).toHaveBeenCalledWith(linksAnother.id, {
      expectedVersion: linksAnother.version,
      scenarioId: differentFrozen.id,
    });

    workflowSpy.mockRestore();
    linkSpy.mockRestore();
  });
});
