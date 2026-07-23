import type {
  GuidedEventMetadata,
  GuidedIntervention,
  GuidedSourceMethod,
  GuidedWorkflow,
} from './api/types';

export const FACTORY_GUIDED_HANDOFF_KEY = 'eventshock:guided-factory-handoff:v1';
export const SCENARIO_GUIDED_HANDOFF_KEY = 'eventshock:guided-scenario-handoff:v1';
const GUIDED_HANDOFF_OWNER_KEY = 'eventshock:guided-handoff-owner:v1';

const HANDOFF_MAX_AGE_MS = 24 * 60 * 60 * 1_000;
const SOURCE_METHODS = new Set<GuidedSourceMethod>([
  'PASTE',
  'WEB_SEARCH',
  'COMBINED',
  'MANUAL',
]);
const INTERVENTION_PARAMETERS = new Set<GuidedIntervention['parameter']>([
  'marketMakerCapacity',
  'socialAmplification',
  'stopLossSensitivity',
  'clarificationDelay',
  'liquidityDepthMultiplier',
  'passiveFlowMultiplier',
  'informationLatency',
]);
const INTERVENTION_MAXIMUMS: Readonly<Record<GuidedIntervention['parameter'], number>> = {
  marketMakerCapacity: 3,
  socialAmplification: 3,
  stopLossSensitivity: 3,
  clarificationDelay: 4,
  liquidityDepthMultiplier: 3,
  passiveFlowMultiplier: 3,
  informationLatency: 4,
};

export interface FactoryGuidedHandoff {
  schemaVersion: '1.1.0';
  ownerUserId: string;
  workflowId: string;
  createdAt: string;
  eventMetadata: GuidedEventMetadata;
  sourceMethod: GuidedSourceMethod;
  searchQueries: string[];
}

export interface ScenarioGuidedHandoff {
  schemaVersion: '1.1.0';
  ownerUserId: string;
  workflowId: string;
  createdAt: string;
  eventPackId: string;
  eventMetadata: GuidedEventMetadata;
  intervention: GuidedIntervention;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isBoundedString(value: unknown, minimum: number, maximum: number): value is string {
  return typeof value === 'string'
    && value.trim().length >= minimum
    && value.length <= maximum;
}

function isCurrent(createdAt: unknown): createdAt is string {
  if (!isBoundedString(createdAt, 10, 64)) return false;
  const timestamp = Date.parse(createdAt);
  return Number.isFinite(timestamp)
    && timestamp <= Date.now() + 60_000
    && Date.now() - timestamp <= HANDOFF_MAX_AGE_MS;
}

function isEventMetadata(value: unknown): value is GuidedEventMetadata {
  if (!isRecord(value)) return false;
  return isBoundedString(value.title, 1, 200)
    && (value.titleZh === undefined || isBoundedString(value.titleZh, 1, 200))
    && isBoundedString(value.summary, 1, 1_000)
    && (value.summaryZh === undefined || isBoundedString(value.summaryZh, 1, 1_000))
    && isBoundedString(value.instrument, 1, 32)
    && isBoundedString(value.asOf, 10, 64)
    && Number.isFinite(Date.parse(value.asOf))
    && isBoundedString(value.researchQuestion, 1, 500);
}

function isIntervention(value: unknown): value is GuidedIntervention {
  if (!isRecord(value)) return false;
  if (
    typeof value.parameter !== 'string'
    || !INTERVENTION_PARAMETERS.has(value.parameter as GuidedIntervention['parameter'])
    || typeof value.baselineValue !== 'number'
    || !Number.isFinite(value.baselineValue)
    || typeof value.interventionValue !== 'number'
    || !Number.isFinite(value.interventionValue)
  ) {
    return false;
  }
  const parameter = value.parameter as GuidedIntervention['parameter'];
  const maximum = INTERVENTION_MAXIMUMS[parameter];
  return value.baselineValue > 0
    && value.baselineValue <= maximum
    && value.interventionValue > 0
    && value.interventionValue <= maximum
    && value.baselineValue !== value.interventionValue
    && isBoundedString(value.explanation, 1, 1_000);
}

function isOwnerUserId(value: unknown): value is string {
  return isBoundedString(value, 3, 128)
    && /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value);
}

function currentOwnerUserId(): string | undefined {
  try {
    const value = window.sessionStorage.getItem(GUIDED_HANDOFF_OWNER_KEY);
    if (isOwnerUserId(value)) return value;
    window.sessionStorage.removeItem(GUIDED_HANDOFF_OWNER_KEY);
  } catch {
    return undefined;
  }
  return undefined;
}

export function guidedHandoffStorageKey(baseKey: string, ownerUserId: string): string {
  return `${baseKey}:${encodeURIComponent(ownerUserId)}`;
}

function removeOwnerHandoffs(ownerUserId: string): void {
  window.sessionStorage.removeItem(guidedHandoffStorageKey(
    FACTORY_GUIDED_HANDOFF_KEY,
    ownerUserId,
  ));
  window.sessionStorage.removeItem(guidedHandoffStorageKey(
    SCENARIO_GUIDED_HANDOFF_KEY,
    ownerUserId,
  ));
}

/**
 * 将当前标签页的临时交接数据绑定到已认证账号。
 * 切换账号、退出或会话过期时销毁旧账号数据，防止共享标签页串号。
 */
export function synchronizeGuidedHandoffOwner(ownerUserId?: string): void {
  const previousOwnerUserId = currentOwnerUserId();
  window.sessionStorage.removeItem(FACTORY_GUIDED_HANDOFF_KEY);
  window.sessionStorage.removeItem(SCENARIO_GUIDED_HANDOFF_KEY);
  if (previousOwnerUserId && previousOwnerUserId !== ownerUserId) {
    removeOwnerHandoffs(previousOwnerUserId);
  }
  if (!ownerUserId) {
    if (previousOwnerUserId) removeOwnerHandoffs(previousOwnerUserId);
    window.sessionStorage.removeItem(GUIDED_HANDOFF_OWNER_KEY);
    return;
  }
  if (!isOwnerUserId(ownerUserId)) {
    throw new Error('Authenticated user ID is not safe for guided handoff storage.');
  }
  window.sessionStorage.setItem(GUIDED_HANDOFF_OWNER_KEY, ownerUserId);
}

function readSessionValue<T>(
  baseKey: string,
  validate: (value: unknown) => value is T,
): T | undefined {
  const ownerUserId = currentOwnerUserId();
  if (!ownerUserId) return undefined;
  const key = guidedHandoffStorageKey(baseKey, ownerUserId);
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return undefined;
    const parsed: unknown = JSON.parse(raw);
    if (validate(parsed)) return parsed;
    window.sessionStorage.removeItem(key);
  } catch {
    window.sessionStorage.removeItem(key);
  }
  return undefined;
}

function writeSessionValue(baseKey: string, value: object): void {
  const ownerUserId = currentOwnerUserId();
  if (!ownerUserId) {
    throw new Error('An authenticated user is required before creating a guided handoff.');
  }
  const key = guidedHandoffStorageKey(baseKey, ownerUserId);
  window.sessionStorage.setItem(key, JSON.stringify(value));
}

export function writeFactoryGuidedHandoff(workflow: GuidedWorkflow): void {
  if (!workflow.draft.eventMetadata || !workflow.draft.sourceMethod) {
    throw new Error('Guided event metadata and source method must be reviewed first.');
  }
  const ownerUserId = currentOwnerUserId();
  if (!ownerUserId) {
    throw new Error('An authenticated user is required before creating a guided handoff.');
  }
  writeSessionValue(FACTORY_GUIDED_HANDOFF_KEY, {
    schemaVersion: '1.1.0',
    ownerUserId,
    workflowId: workflow.id,
    createdAt: new Date().toISOString(),
    eventMetadata: workflow.draft.eventMetadata,
    sourceMethod: workflow.draft.sourceMethod,
    searchQueries: workflow.draft.searchQueries.slice(0, 8),
  } satisfies FactoryGuidedHandoff);
}

export function readFactoryGuidedHandoff(): FactoryGuidedHandoff | undefined {
  return readSessionValue(
    FACTORY_GUIDED_HANDOFF_KEY,
    (value): value is FactoryGuidedHandoff => {
      if (!isRecord(value)) return false;
      return value.schemaVersion === '1.1.0'
        && value.ownerUserId === currentOwnerUserId()
        && isBoundedString(value.workflowId, 8, 128)
        && isCurrent(value.createdAt)
        && isEventMetadata(value.eventMetadata)
        && typeof value.sourceMethod === 'string'
        && SOURCE_METHODS.has(value.sourceMethod as GuidedSourceMethod)
        && Array.isArray(value.searchQueries)
        && value.searchQueries.length <= 8
        && value.searchQueries.every((query) => isBoundedString(query, 1, 200));
    },
  );
}

export function clearFactoryGuidedHandoff(): void {
  const ownerUserId = currentOwnerUserId();
  if (ownerUserId) {
    window.sessionStorage.removeItem(guidedHandoffStorageKey(
      FACTORY_GUIDED_HANDOFF_KEY,
      ownerUserId,
    ));
  }
}

export function writeScenarioGuidedHandoff(workflow: GuidedWorkflow): void {
  if (
    !workflow.draft.eventMetadata
    || !workflow.draft.eventPackId
    || !workflow.draft.intervention
  ) {
    throw new Error('A reviewed Event Pack and intervention must be linked first.');
  }
  const ownerUserId = currentOwnerUserId();
  if (!ownerUserId) {
    throw new Error('An authenticated user is required before creating a guided handoff.');
  }
  writeSessionValue(SCENARIO_GUIDED_HANDOFF_KEY, {
    schemaVersion: '1.1.0',
    ownerUserId,
    workflowId: workflow.id,
    createdAt: new Date().toISOString(),
    eventPackId: workflow.draft.eventPackId,
    eventMetadata: workflow.draft.eventMetadata,
    intervention: workflow.draft.intervention,
  } satisfies ScenarioGuidedHandoff);
}

export function readScenarioGuidedHandoff(): ScenarioGuidedHandoff | undefined {
  return readSessionValue(
    SCENARIO_GUIDED_HANDOFF_KEY,
    (value): value is ScenarioGuidedHandoff => {
      if (!isRecord(value)) return false;
      return value.schemaVersion === '1.1.0'
        && value.ownerUserId === currentOwnerUserId()
        && isBoundedString(value.workflowId, 8, 128)
        && isCurrent(value.createdAt)
        && isBoundedString(value.eventPackId, 3, 128)
        && isEventMetadata(value.eventMetadata)
        && isIntervention(value.intervention);
    },
  );
}

export function clearScenarioGuidedHandoff(): void {
  const ownerUserId = currentOwnerUserId();
  if (ownerUserId) {
    window.sessionStorage.removeItem(guidedHandoffStorageKey(
      SCENARIO_GUIDED_HANDOFF_KEY,
      ownerUserId,
    ));
  }
}
