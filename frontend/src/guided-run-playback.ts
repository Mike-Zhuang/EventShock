import type { CognitionProgress, Experiment, ExperimentStatus } from './api/types';

const STORAGE_KEY = 'eventshock-guided-run-playback-v1';
const DEFAULT_DURATION_MS = 78_000;
const MAX_PLAYBACK_AGE_MS = 15 * 60 * 1_000;

export interface GuidedRunPlayback {
  experimentId: string;
  startedAtMs: number;
  durationMs: number;
}

export type GuidedRunPhase = 'QUEUED' | 'COGNITION' | 'PAIRED_RUNS' | 'AGGREGATING' | 'COMPLETED';

export interface GuidedRunPresentation {
  phase: GuidedRunPhase;
  status: ExperimentStatus;
  progress: number;
  validSeeds: number;
  message: string;
  cognitionProgress?: CognitionProgress;
}

export function startGuidedRunPlayback(
  experimentId: string,
  durationMs = DEFAULT_DURATION_MS,
): GuidedRunPlayback {
  const playback = {
    experimentId,
    startedAtMs: Date.now(),
    durationMs: Math.max(20_000, durationMs),
  };
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(playback));
  return playback;
}

export function readGuidedRunPlayback(): GuidedRunPlayback | undefined {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return undefined;
    const value = JSON.parse(raw) as Partial<GuidedRunPlayback>;
    if (
      typeof value.experimentId !== 'string'
      || typeof value.startedAtMs !== 'number'
      || typeof value.durationMs !== 'number'
      || Date.now() - value.startedAtMs > MAX_PLAYBACK_AGE_MS
    ) {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return undefined;
    }
    return value as GuidedRunPlayback;
  } catch {
    window.sessionStorage.removeItem(STORAGE_KEY);
    return undefined;
  }
}

export function guidedRunPresentation(
  playback: GuidedRunPlayback,
  experiment: Experiment,
  nowMs: number,
  language: 'en' | 'zh-CN',
): GuidedRunPresentation {
  const elapsedRatio = Math.min(
    1,
    Math.max(0, (nowMs - playback.startedAtMs) / playback.durationMs),
  );
  const totalSeeds = Math.max(experiment.totalSeeds ?? 10, 1);
  const finalCognition = experiment.liveState?.cognitionProgress;
  const plannedCalls = Math.max(
    finalCognition?.plannedCalls
      ?? experiment.scenario?.llmPolicy?.callBudget
      ?? 4,
    1,
  );
  const isZh = language === 'zh-CN';

  if (elapsedRatio < 0.07) {
    return {
      phase: 'QUEUED',
      status: 'QUEUED',
      progress: Math.max(1, elapsedRatio / 0.07 * 5),
      validSeeds: 0,
      message: isZh ? '正在装载冻结 Event Pack 与情景配置。' : 'Loading the frozen Event Pack and scenario configuration.',
    };
  }

  if (elapsedRatio < 0.38) {
    const cognitionRatio = (elapsedRatio - 0.07) / 0.31;
    const attemptedCalls = Math.min(plannedCalls, Math.max(1, Math.ceil(cognitionRatio * plannedCalls)));
    const completedCalls = Math.min(plannedCalls, Math.floor(cognitionRatio * plannedCalls));
    const validationStage = cognitionRatio > 0.72;
    return {
      phase: 'COGNITION',
      status: 'RUNNING',
      progress: 5 + cognitionRatio * 23,
      validSeeds: 0,
      message: validationStage
        ? isZh ? '正在校验并冻结 LLM 结构化认知决策。' : 'Validating and freezing structured LLM cognition decisions.'
        : isZh ? '外部 LLM 正在生成证据约束的信念与行动偏好。' : 'The external LLM is generating evidence-bound beliefs and action preferences.',
      cognitionProgress: {
        ...finalCognition,
        status: validationStage ? 'MODEL_VALIDATING' : 'MODEL_STREAM_RECEIVING',
        plannedCalls,
        attemptedCalls,
        completedCalls,
        fallbackCount: 0,
        totalTokens: Math.round((finalCognition?.totalTokens ?? 0) * cognitionRatio),
      },
    };
  }

  if (elapsedRatio < 0.88) {
    const pairRatio = (elapsedRatio - 0.38) / 0.5;
    const validSeeds = Math.min(totalSeeds, Math.floor(pairRatio * totalSeeds));
    return {
      phase: 'PAIRED_RUNS',
      status: 'RUNNING',
      progress: 28 + pairRatio * 62,
      validSeeds,
      message: isZh
        ? `正在运行第 ${Math.min(totalSeeds, validSeeds + 1)} / ${totalSeeds} 组基准与干预配对。`
        : `Running baseline and intervention pair ${Math.min(totalSeeds, validSeeds + 1)} of ${totalSeeds}.`,
      cognitionProgress: finalCognition,
    };
  }

  if (elapsedRatio < 1) {
    const aggregationRatio = (elapsedRatio - 0.88) / 0.12;
    return {
      phase: 'AGGREGATING',
      status: 'AGGREGATING',
      progress: 90 + aggregationRatio * 9,
      validSeeds: totalSeeds,
      message: isZh
        ? '正在汇总配对分布、经验区间、机制链路与可复现元数据。'
        : 'Aggregating paired distributions, empirical intervals, mechanism traces, and reproducibility metadata.',
      cognitionProgress: finalCognition,
    };
  }

  return {
    phase: 'COMPLETED',
    status: experiment.status,
    progress: experiment.progress,
    validSeeds: experiment.validSeeds ?? totalSeeds,
    message: experiment.message
      ?? (isZh ? '实验与全部验证检查已完成。' : 'The experiment and all validation checks are complete.'),
    cognitionProgress: finalCognition,
  };
}
