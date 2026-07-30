import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { GuidedWorkflow } from '../api/types';
import { readGuidedReturnContext } from '../guided-handoff';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { GuidedWorkflowPage } from './guided-workflow-page';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getGuidedWorkflows: vi.fn(),
      getGuidedWorkflow: vi.fn(),
      getGuidedTurnOperations: vi.fn(),
    },
  };
});

vi.mock('../guided-handoff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../guided-handoff')>();
  return {
    ...actual,
    readGuidedReturnContext: vi.fn(),
  };
});

vi.mock('../state/workflow-context', () => ({
  useWorkflow: vi.fn(),
}));

function workflow(id: string): GuidedWorkflow {
  return {
    schemaVersion: '1.0.0',
    id,
    stage: 'CLAIM_REVIEW',
    status: 'ACTIVE',
    version: 3,
    language: 'en',
    draft: {
      searchQueries: [],
      eventPackId: 'pack-reviewed',
    },
    messages: [],
    createdAt: '2026-07-20T10:00:00Z',
    updatedAt: '2026-07-20T11:00:00Z',
  };
}

describe('GuidedWorkflowPage 职责地图与返回续接', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('ResizeObserver', vi.fn().mockImplementation(() => ({
      observe: vi.fn(),
      unobserve: vi.fn(),
      disconnect: vi.fn(),
    })));
    vi.mocked(useWorkflow).mockReturnValue({
      selectCase: vi.fn(),
      setScenario: vi.fn(),
    } as unknown as ReturnType<typeof useWorkflow>);
    vi.mocked(api.getGuidedTurnOperations).mockResolvedValue([]);
    vi.mocked(readGuidedReturnContext).mockReturnValue(undefined);
  });

  it('完整说明证据、主张、冻结和启动必须由人负责的原因', async () => {
    vi.mocked(api.getGuidedWorkflows).mockResolvedValue([]);

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('heading', {
      name: 'End-to-end AI and human responsibilities',
    })).toBeInTheDocument();
    expect(screen.getByText(/source authorization require a human decision/i))
      .toBeInTheDocument();
    expect(screen.getByText(/AI cannot replace the accountable evidence judgment/i))
      .toBeInTheDocument();
    expect(screen.getByText(/locks the exact inputs used for reproducibility/i))
      .toBeInTheDocument();
    expect(screen.getByText(/provider fees and carries interpretation responsibility/i))
      .toBeInTheDocument();
  });

  it('返回时优先读取同一引导的服务器状态，而不是列表第一项', async () => {
    const first = workflow('guided-first-0001');
    const returned = workflow('guided-returned-0002');
    vi.mocked(api.getGuidedWorkflows).mockResolvedValue([first, returned]);
    vi.mocked(api.getGuidedWorkflow).mockImplementation(async (id) => (
      id === returned.id ? returned : first
    ));
    vi.mocked(readGuidedReturnContext).mockReturnValue({
      schemaVersion: '1.0.0',
      ownerUserId: 'owner-one',
      workflowId: returned.id,
      stage: returned.stage,
      createdAt: new Date().toISOString(),
    });

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(api.getGuidedWorkflow).toHaveBeenCalledWith(returned.id);
    });
    expect(screen.getByLabelText('Saved workflows')).toHaveValue(returned.id);
  });
});
