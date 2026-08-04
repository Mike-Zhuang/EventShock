import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type {
  CognitionEvalSummary,
  DeploymentStatus,
  GovernanceInventory,
  RedTeamRegistry,
  ReleaseGateView,
  SystemMetrics,
  ValidationLadderView,
} from '../api/types';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { GovernancePage } from './governance-page';

vi.mock('../api/client', () => ({
  api: {
    getGovernanceInventory: vi.fn(),
    getRedTeamRegistry: vi.fn(),
    getReleaseGate: vi.fn(),
    getValidationLadder: vi.fn(),
    getEvalSummary: vi.fn(),
    getSystemMetrics: vi.fn(),
    getDeploymentStatus: vi.fn(),
  },
}));

vi.mock('../state/workflow-context', () => ({
  useWorkflow: vi.fn(),
}));

const DEPLOYED_COMMIT = 'a'.repeat(40);
const GITHUB_MAIN_COMMIT = 'b'.repeat(40);

const INVENTORY: GovernanceInventory = {
  inventoryHash: 'sha256:governance-inventory',
  items: [],
};

const RED_TEAM: RedTeamRegistry = {
  definitions: [],
  results: [],
  notice: 'No red-team execution evidence is available.',
};

const RELEASE_GATE: ReleaseGateView = {
  releaseId: 'release-candidate-1',
  evaluatedAt: '2026-07-29T10:00:00Z',
  decision: 'BLOCKED',
  canRelease: false,
  inventoryHash: INVENTORY.inventoryHash,
  humanEvidenceComplete: false,
  blockerGateIds: ['p0-model-validation-review'],
  blockerCategoryCounts: { MODEL_VALIDATION_REVIEW: 1 },
  blockerSummaries: [{
    gateId: 'p0-model-validation-review',
    category: 'MODEL_VALIDATION_REVIEW',
    status: 'PENDING_HUMAN_EVIDENCE',
    owner: 'LLM & Evaluation Lead',
    requiredEvidence: 'MODEL_VALIDATION_REVIEW',
    evidenceIds: [],
    actionTarget: '#gate-p0-model-validation-review',
  }],
  useCaseAxes: [{
    axisId: 'CONTROLLED_DEMO',
    label: 'Controlled educational demo',
    status: 'ALLOWED_WITH_BOUNDARIES',
    boundary: 'Synthetic mechanism demonstration only.',
  }, {
    axisId: 'INTERNAL_RESEARCH_PROTOTYPE',
    label: 'Internal research prototype',
    status: 'ALLOWED_WITH_BOUNDARIES',
    boundary: 'Exploratory internal use only.',
  }, {
    axisId: 'REAL_WORLD_PREDICTIVE_CLAIM',
    label: 'Real-world predictive claim',
    status: 'BLOCKED',
    boundary: 'No external predictive validation.',
  }, {
    axisId: 'INVESTMENT_DECISION',
    label: 'Investment decision support',
    status: 'PROHIBITED',
    boundary: 'Not investment advice.',
  }, {
    axisId: 'PRODUCTION_EXTERNAL_VALIDATION',
    label: 'Production / external validation',
    status: 'BLOCKED',
    boundary: 'External evidence is pending.',
  }],
  gateResults: [{
    gateId: 'p0-model-validation-review',
    status: 'PENDING_HUMAN_EVIDENCE',
    detail: 'Human model validation is pending.',
    evidenceIds: [],
  }],
  definitions: [{
    gateId: 'p0-model-validation-review',
    title: 'LLM behavior receives human validation',
    owner: 'LLM & Evaluation Lead',
    criterion: 'A named reviewer examines live-model outputs.',
    failureEffect: 'Release remains blocked.',
  }],
  interpretationBoundary: 'MECHANISM_DEMONSTRATION_NOT_PRODUCTION_EVIDENCE',
};

const VALIDATION_LADDER: ValidationLadderView = {
  highestAllowedClaim: 'MECHANISM_DEMONSTRATION',
  levels: [],
};

const TELEMETRY = {
  calls: 0,
  cacheHits: 0,
  fallbacks: 0,
  invalidOutputs: 0,
  promptTokens: 0,
  completionTokens: 0,
  cachedTokens: 0,
  totalTokens: 0,
  totalLatencyMs: 0,
  averageLatencyMs: 0,
  cacheHitRate: 0,
  fallbackRate: 0,
  invalidOutputRate: 0,
  structuredSuccesses: 0,
  structuredSuccessRate: 0,
  structuredSuccessThreshold: 0.95,
  structuredSuccessGateStatus: 'NOT_EVALUATED',
  failureCategoryCounts: {},
  observationScope: 'PERSISTED_SITE_WIDE',
};

const EVAL_SUMMARY: CognitionEvalSummary = {
  telemetry: TELEMETRY,
  evaluatedCases: 0,
  passedCases: 0,
  passRate: 0,
};

const SYSTEM_METRICS: SystemMetrics = {
  service: 'eventshock-api',
  version: '0.3.0',
  runtime: {
    uptimeSeconds: 120,
    requestCount: 10,
    clientErrorCount: 0,
    serverErrorCount: 0,
    serverErrorRate: 0,
    latencyWindowSize: 10,
    latencyMs: {
      p50: 4,
      p95: 8,
      maximum: 9,
      mean: 5,
    },
    privacyBoundary: 'NO_PATH_BODY_SESSION_OR_CREDENTIAL_LABELS',
  },
  experiments: {
    workerConcurrency: 1,
    activeOrQueued: 0,
    maximumActiveOrQueued: 8,
    maximumExperimentsPerSession: 30,
  },
  storage: {
    database: 'ok',
    retainedExperiments: 0,
    maximumRetainedExperiments: 500,
  },
  cognition: TELEMETRY,
  sloTargets: {
    availability: 0.99,
    apiP95Milliseconds: 750,
    status: 'TARGETS_NOT_PRODUCTION_EVIDENCE',
  },
};

const DEPLOYMENT_STATUS: DeploymentStatus = {
  schemaVersion: '1.0.0',
  deployedCommit: DEPLOYED_COMMIT,
  healthCommit: DEPLOYED_COMMIT,
  reportedDeployedCommit: DEPLOYED_COMMIT,
  githubMainCommit: GITHUB_MAIN_COMMIT,
  branch: 'main',
  commitAlignment: 'MAIN_MISMATCH',
  requiredChecks: [
    {
      name: 'Backend / Python 3.12.13',
      status: 'PASS',
      completedAt: '2026-07-29T10:01:00Z',
    },
    {
      name: 'Frontend / Node 22',
      status: 'PENDING',
    },
    {
      name: 'Production container',
      status: 'UNKNOWN',
    },
  ],
  requiredChecksStatus: 'FAIL',
  lastSyncAt: '2026-07-29T10:05:00Z',
  lastSyncResult: 'FAILED',
  lastDeployAt: '2026-07-28T18:30:00Z',
  lastFailureAt: '2026-07-29T10:05:00Z',
  lastFailureCode: 'REQUIRED_CHECKS_FAILED',
  evidenceObservedAt: '2026-07-29T10:06:00Z',
  statusSource: 'RESTRICTED_STATUS_FILE',
  statusFileState: 'VERIFIED',
  observedAt: '2026-07-29T10:07:00Z',
};

describe('GovernancePage 生产部署直接证据', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(useWorkflow).mockReturnValue({
      results: undefined,
    } as ReturnType<typeof useWorkflow>);
    vi.mocked(api.getGovernanceInventory).mockResolvedValue(INVENTORY);
    vi.mocked(api.getRedTeamRegistry).mockResolvedValue(RED_TEAM);
    vi.mocked(api.getReleaseGate).mockResolvedValue(RELEASE_GATE);
    vi.mocked(api.getValidationLadder).mockResolvedValue(VALIDATION_LADDER);
    vi.mocked(api.getEvalSummary).mockResolvedValue(EVAL_SUMMARY);
    vi.mocked(api.getSystemMetrics).mockResolvedValue(SYSTEM_METRICS);
    vi.mocked(api.getDeploymentStatus).mockResolvedValue(DEPLOYMENT_STATUS);
  });

  it('shows the deployed and main SHAs, all three required checks, and the public-evidence boundary', async () => {
    render(<I18nProvider><GovernancePage /></I18nProvider>);

    expect(await screen.findByRole('heading', {
      name: 'Direct production deployment evidence',
    })).toBeInTheDocument();
    expect(screen.getByText(DEPLOYED_COMMIT)).toBeInTheDocument();
    expect(screen.getByText(GITHUB_MAIN_COMMIT)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: DEPLOYED_COMMIT })).toHaveAttribute(
      'href',
      `https://github.com/Mike-Zhuang/EventShock/commit/${DEPLOYED_COMMIT}`,
    );
    expect(screen.getByRole('link', { name: GITHUB_MAIN_COMMIT })).toHaveAttribute(
      'href',
      `https://github.com/Mike-Zhuang/EventShock/commit/${GITHUB_MAIN_COMMIT}`,
    );
    const useBoundaryHeading = screen.getByRole('heading', {
      name: 'Five-axis use boundary status',
    });
    expect(useBoundaryHeading).toBeInTheDocument();
    const useBoundarySection = useBoundaryHeading.closest('section');
    expect(useBoundarySection).not.toBeNull();
    const useBoundaryView = within(useBoundarySection as HTMLElement);
    expect(useBoundaryView.getByText('Investment decision support')).toBeInTheDocument();
    const prohibitedTag = useBoundaryView.getByText('PROHIBITED').closest('.cds--tag');
    const blockedTags = useBoundaryView
      .getAllByText('BLOCKED')
      .map((item) => item.closest('.cds--tag'));
    expect(prohibitedTag).toHaveClass('governance-status--prohibited');
    blockedTags.forEach((tag) => expect(tag).not.toHaveClass('governance-status--prohibited'));
    expect(screen.getByRole('link', { name: 'Review action' })).toHaveAttribute(
      'href',
      '#gate-p0-model-validation-review',
    );

    const backendRow = screen.getByText('Backend / Python 3.12.13').closest('tr');
    const frontendRow = screen.getByText('Frontend / Node 22').closest('tr');
    const containerRow = screen.getByText('Production container').closest('tr');
    expect(backendRow).not.toBeNull();
    expect(frontendRow).not.toBeNull();
    expect(containerRow).not.toBeNull();
    expect(within(backendRow as HTMLTableRowElement).getByText('PASS')).toBeInTheDocument();
    expect(within(frontendRow as HTMLTableRowElement).getByText('PENDING')).toBeInTheDocument();
    expect(within(containerRow as HTMLTableRowElement).getByText('UNKNOWN')).toBeInTheDocument();

    expect(screen.getByText('REQUIRED_CHECKS_FAILED')).toBeInTheDocument();
    expect(screen.getByText('RESTRICTED STATUS FILE')).toBeInTheDocument();
    expect(screen.getByText(
      'Synchronization logs do not replace direct public evidence',
    )).toBeInTheDocument();
  });

  it('provides equivalent Simplified Chinese status and evidence-boundary copy', async () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    render(<I18nProvider><GovernancePage /></I18nProvider>);

    expect(await screen.findByRole('heading', { name: '生产部署直接证据' }))
      .toBeInTheDocument();
    expect(screen.getByText('同步日志不能替代公网直接证据')).toBeInTheDocument();
    expect(screen.getByText('运行中进程的健康 SHA 是当前部署版本的权威来源；受限状态文件只补充 GitHub main、CI 和同步时间。'))
      .toBeInTheDocument();
    expect(screen.getByText('三项必需检查: 失败')).toBeInTheDocument();

    const frontendRow = screen.getByText('Frontend / Node 22').closest('tr');
    const containerRow = screen.getByText('Production container').closest('tr');
    expect(within(frontendRow as HTMLTableRowElement).getByText('等待中'))
      .toBeInTheDocument();
    expect(within(containerRow as HTMLTableRowElement).getByText('未知'))
      .toBeInTheDocument();
  });
});
