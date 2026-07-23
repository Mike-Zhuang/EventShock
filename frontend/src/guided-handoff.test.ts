import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GuidedWorkflow } from './api/types';
import {
  FACTORY_GUIDED_HANDOFF_KEY,
  SCENARIO_GUIDED_HANDOFF_KEY,
  clearFactoryGuidedHandoff,
  clearScenarioGuidedHandoff,
  guidedHandoffStorageKey,
  readFactoryGuidedHandoff,
  readScenarioGuidedHandoff,
  synchronizeGuidedHandoffOwner,
  writeFactoryGuidedHandoff,
  writeScenarioGuidedHandoff,
} from './guided-handoff';

const OWNER_USER_ID = 'guided-owner-0001';

const workflow: GuidedWorkflow = {
  schemaVersion: '1.0.0',
  id: 'guided-12345678',
  stage: 'SCENARIO_INTERVENTION',
  status: 'ACTIVE',
  version: 6,
  language: 'en',
  draft: {
    eventMetadata: {
      title: 'Index inclusion event',
      titleZh: '指数纳入事件',
      summary: 'A bounded event summary for human review.',
      summaryZh: '供人工复核的有界事件摘要。',
      instrument: 'TEST',
      asOf: '2026-07-22T10:00:00Z',
      researchQuestion: 'How does one liquidity intervention propagate?',
    },
    sourceMethod: 'COMBINED',
    searchQueries: ['official index inclusion notice'],
    intervention: {
      parameter: 'marketMakerCapacity',
      baselineValue: 1,
      interventionValue: 0.45,
      explanation: 'Compare one bounded liquidity-capacity change.',
    },
    eventPackId: 'event-pack-12345678',
  },
  messages: [],
  createdAt: '2026-07-22T10:00:00Z',
  updatedAt: '2026-07-22T10:10:00Z',
};

// 交接数据现在按已认证账号作用域存储；测试需先绑定 owner，模拟真实登录态。
describe('guided handoff storage', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.useRealTimers();
    synchronizeGuidedHandoffOwner(OWNER_USER_ID);
  });

  it('stores only bounded proposal fields for Factory prefill', () => {
    writeFactoryGuidedHandoff(workflow);

    expect(readFactoryGuidedHandoff()).toMatchObject({
      ownerUserId: OWNER_USER_ID,
      workflowId: workflow.id,
      sourceMethod: 'COMBINED',
      searchQueries: ['official index inclusion notice'],
      eventMetadata: { instrument: 'TEST' },
    });
  });

  it('stores the reviewed Event Pack and intervention for Scenario prefill', () => {
    writeScenarioGuidedHandoff(workflow);

    expect(readScenarioGuidedHandoff()).toMatchObject({
      ownerUserId: OWNER_USER_ID,
      workflowId: workflow.id,
      eventPackId: 'event-pack-12345678',
      intervention: {
        parameter: 'marketMakerCapacity',
        baselineValue: 1,
        interventionValue: 0.45,
      },
    });
  });

  it('discards malformed and expired values instead of trusting storage', () => {
    const factoryKey = guidedHandoffStorageKey(FACTORY_GUIDED_HANDOFF_KEY, OWNER_USER_ID);
    window.sessionStorage.setItem(
      factoryKey,
      JSON.stringify({ schemaVersion: '1.0.0', workflowId: '<script>' }),
    );
    expect(readFactoryGuidedHandoff()).toBeUndefined();
    expect(window.sessionStorage.getItem(factoryKey)).toBeNull();

    const scenarioKey = guidedHandoffStorageKey(SCENARIO_GUIDED_HANDOFF_KEY, OWNER_USER_ID);
    window.sessionStorage.setItem(
      scenarioKey,
      JSON.stringify({
        schemaVersion: '1.1.0',
        ownerUserId: OWNER_USER_ID,
        workflowId: workflow.id,
        createdAt: '2020-01-01T00:00:00Z',
        eventPackId: workflow.draft.eventPackId,
        eventMetadata: workflow.draft.eventMetadata,
        intervention: workflow.draft.intervention,
      }),
    );
    expect(readScenarioGuidedHandoff()).toBeUndefined();
    expect(window.sessionStorage.getItem(scenarioKey)).toBeNull();
  });

  it('discards intervention values outside the server contract', () => {
    const scenarioKey = guidedHandoffStorageKey(SCENARIO_GUIDED_HANDOFF_KEY, OWNER_USER_ID);
    window.sessionStorage.setItem(
      scenarioKey,
      JSON.stringify({
        schemaVersion: '1.1.0',
        ownerUserId: OWNER_USER_ID,
        workflowId: workflow.id,
        createdAt: new Date().toISOString(),
        eventPackId: workflow.draft.eventPackId,
        eventMetadata: workflow.draft.eventMetadata,
        intervention: {
          ...workflow.draft.intervention,
          parameter: 'marketMakerCapacity',
          interventionValue: 3.5,
        },
      }),
    );

    expect(readScenarioGuidedHandoff()).toBeUndefined();
    expect(window.sessionStorage.getItem(scenarioKey)).toBeNull();
  });

  it('clears completed handoffs so a later visit cannot reapply stale drafts', () => {
    writeFactoryGuidedHandoff(workflow);
    writeScenarioGuidedHandoff(workflow);

    clearFactoryGuidedHandoff();
    clearScenarioGuidedHandoff();

    expect(readFactoryGuidedHandoff()).toBeUndefined();
    expect(readScenarioGuidedHandoff()).toBeUndefined();
  });

  it('isolates handoffs per account so a second user in the same tab cannot read them', () => {
    writeFactoryGuidedHandoff(workflow);
    writeScenarioGuidedHandoff(workflow);
    expect(readFactoryGuidedHandoff()).toBeDefined();

    // 同一浏览器标签页切换到另一个账号后，前一账号的交接数据必须不可见且被销毁。
    synchronizeGuidedHandoffOwner('guided-owner-0002');
    expect(readFactoryGuidedHandoff()).toBeUndefined();
    expect(readScenarioGuidedHandoff()).toBeUndefined();

    // 切回原账号也不能再读到已被销毁的旧数据，避免串号泄漏研究元数据。
    synchronizeGuidedHandoffOwner(OWNER_USER_ID);
    expect(readFactoryGuidedHandoff()).toBeUndefined();
    expect(readScenarioGuidedHandoff()).toBeUndefined();
  });

  it('clears handoffs when the session ends so a later login cannot reapply them', () => {
    writeFactoryGuidedHandoff(workflow);
    writeScenarioGuidedHandoff(workflow);

    // 退出登录（无 owner）应清理当前账号的全部交接数据。
    synchronizeGuidedHandoffOwner();
    synchronizeGuidedHandoffOwner(OWNER_USER_ID);
    expect(readFactoryGuidedHandoff()).toBeUndefined();
    expect(readScenarioGuidedHandoff()).toBeUndefined();
  });
});
