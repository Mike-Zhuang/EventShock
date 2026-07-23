import type { ResultInterpretationToolActivity } from '../api/types';
import { describe, expect, it } from 'vitest';
import {
  RESULT_EVIDENCE_DEFINITIONS,
  RESULT_EVIDENCE_IDS,
  auditResultEvidence,
  buildResultEvidenceNumbering,
  extractResultEvidenceReferences,
  getLocalizedResultEvidence,
  replaceResultEvidenceReferencesWithMarkers,
  sanitizeResultEvidencePlainText,
  splitResultEvidenceText,
} from './result-evidence';

function activity(
  evidenceId: string,
  tool: string,
  overrides: Partial<ResultInterpretationToolActivity> = {},
): ResultInterpretationToolActivity {
  return {
    evidenceId,
    tool,
    label: tool,
    itemCount: 2,
    truncated: false,
    ...overrides,
  };
}

describe('result evidence registry', () => {
  it('defines all eleven backend evidence tools with unique locations and bilingual copy', () => {
    expect(RESULT_EVIDENCE_IDS).toHaveLength(11);
    expect(new Set(RESULT_EVIDENCE_IDS).size).toBe(11);
    expect(RESULT_EVIDENCE_DEFINITIONS.map((item) => item.evidenceId)).toEqual(RESULT_EVIDENCE_IDS);
    expect(new Set(RESULT_EVIDENCE_DEFINITIONS.map((item) => item.tool)).size).toBe(11);
    expect(new Set(RESULT_EVIDENCE_DEFINITIONS.map((item) => item.target)).size).toBe(11);

    for (const definition of RESULT_EVIDENCE_DEFINITIONS) {
      expect(definition.label.en).not.toBe('');
      expect(definition.label['zh-CN']).not.toBe('');
      expect(definition.description.en).not.toBe('');
      expect(definition.description['zh-CN']).not.toBe('');
    }
  });

  it('provides an auditable but non-locatable label for an unknown historical reference', () => {
    const legacyEvidence = getLocalizedResultEvidence('result:retired-tool', 'zh-CN');
    expect(legacyEvidence).toMatchObject({
      evidenceId: 'result:retired-tool',
      known: false,
      label: '旧版证据引用',
    });
    expect(legacyEvidence).not.toHaveProperty('target');
    expect(getLocalizedResultEvidence('result:overview', 'en')).toMatchObject({
      known: true,
      label: 'Experiment overview',
      view: 'results',
      target: 'result-overview-heading',
    });
  });
});

describe('result evidence numbering', () => {
  it('numbers first appearances across answer then analysis summary and reuses duplicate numbers', () => {
    const numbering = buildResultEvidenceNumbering(
      'First [result:overview], then [result:metric-summary], then [result:overview].',
      'Check [result:paired-deltas] and [result:metric-summary].',
    );

    expect(numbering.evidenceIds).toEqual([
      'result:overview',
      'result:metric-summary',
      'result:paired-deltas',
    ]);
    expect(numbering.numberByEvidenceId.get('result:overview')).toBe(1);
    expect(numbering.numberByEvidenceId.get('result:metric-summary')).toBe(2);
    expect(numbering.numberByEvidenceId.get('result:paired-deltas')).toBe(3);
  });

  it('extracts backend-compatible legacy IDs without sharing regular-expression state', () => {
    const text = '[result:overview] [result:legacy.v2:detail]';
    expect(extractResultEvidenceReferences(text)).toEqual([
      'result:overview',
      'result:legacy.v2:detail',
    ]);
    expect(extractResultEvidenceReferences(text)).toEqual([
      'result:overview',
      'result:legacy.v2:detail',
    ]);
  });

  it('仅按可见正文的 AST 首次出现编号，不让代码或链接抢占编号', () => {
    const numbering = buildResultEvidenceNumbering(
      '`[result:overview]` and [result:limitations]',
    );
    const segments = splitResultEvidenceText(
      'code [result:overview] then [result:limitations]',
      numbering,
    );

    expect(segments).toEqual([
      { kind: 'text', value: 'code ' },
      { kind: 'citation', value: '[?]', evidenceId: 'result:overview', number: undefined },
      { kind: 'text', value: ' then ' },
      { kind: 'citation', value: '[1]', evidenceId: 'result:limitations', number: 1 },
    ]);
    const replaced = replaceResultEvidenceReferencesWithMarkers(
      'inline `[result:overview]`',
      numbering,
    );
    expect(replaced).toBe('inline `[?]`');
    expect(replaced).not.toContain('result:');
  });

  it('与 Markdown AST 一致地处理实体，并忽略代码、链接、图片和原始 HTML 中的标识', () => {
    const numbering = buildResultEvidenceNumbering(`
\`[result:metric-summary]\`

[[result:paired-deltas]](https://example.com/source)

![chart [result:limitations]](https://example.com/chart.png)

<script>[result:trace]</script>

Decoded [result&#58;overview], then [result:manifest].
`);

    expect(numbering.evidenceIds).toEqual(['result:overview', 'result:manifest']);
    expect(numbering.numberByEvidenceId.get('result:overview')).toBe(1);
    expect(numbering.numberByEvidenceId.get('result:manifest')).toBe(2);
  });

  it('将历史建议中的内部引用替换成当前语言的可读名称', () => {
    expect(sanitizeResultEvidencePlainText(
      'Compare [result:overview] with [result:legacy.v1].',
      'en',
    )).toBe('Compare Experiment overview with Legacy evidence reference.');
    expect(sanitizeResultEvidencePlainText(
      '查看 [result:metric-summary]',
      'zh-CN',
    )).toBe('查看 主要指标');
  });
});

describe('result evidence reconciliation', () => {
  it('returns a clean audit for matching inline, grounding, and tool evidence', () => {
    const audit = auditResultEvidence(
      'The interval is wide [result:metric-summary].',
      'Review paired estimates [result:paired-deltas].',
      ['result:metric-summary', 'result:paired-deltas'],
      [
        activity('result:metric-summary', 'METRIC_SUMMARY'),
        activity('result:paired-deltas', 'PAIRED_DELTAS', { itemCount: 4, truncated: true }),
      ],
    );

    expect(audit.issues).toEqual([]);
    expect(audit.citations).toEqual([
      expect.objectContaining({
        evidenceId: 'result:metric-summary',
        number: 1,
        known: true,
        itemCount: 2,
        issues: [],
      }),
      expect.objectContaining({
        evidenceId: 'result:paired-deltas',
        number: 2,
        truncated: true,
        itemCount: 4,
        issues: [],
      }),
    ]);
  });

  it('reports missing and mismatched evidence channels without inventing citations', () => {
    const audit = auditResultEvidence(
      'Inline only [result:overview].',
      undefined,
      ['result:limitations'],
      [activity('result:trace', 'TRACE')],
    );

    expect(audit.issues).toEqual(['missing', 'mismatch']);
    expect(audit.missingFromGrounding).toEqual(['result:overview']);
    expect(audit.missingFromText).toEqual(['result:limitations']);
    expect(audit.missingToolActivity).toEqual(['result:overview', 'result:limitations']);
    expect(audit.unreferencedToolActivity).toEqual(['result:trace']);
  });

  it('keeps unknown historical references numbered but marks them non-locatable', () => {
    const audit = auditResultEvidence(
      'Legacy evidence [result:retired-tool].',
      undefined,
      ['result:retired-tool'],
      [activity('result:retired-tool', 'RETIRED_TOOL')],
    );

    expect(audit.numbering.numberByEvidenceId.get('result:retired-tool')).toBe(1);
    expect(audit.unknownEvidenceIds).toEqual(['result:retired-tool']);
    expect(audit.issues).toEqual(['unknown']);
    expect(audit.citations[0]).toMatchObject({
      evidenceId: 'result:retired-tool',
      number: 1,
      known: false,
      issues: ['unknown'],
    });
  });

  it('detects when a known evidence ID is reported by the wrong tool', () => {
    const audit = auditResultEvidence(
      'See [result:overview].',
      undefined,
      ['result:overview'],
      [activity('result:overview', 'LIMITATIONS')],
    );

    expect(audit.issues).toEqual(['mismatch']);
    expect(audit.mismatchedToolEvidenceIds).toEqual(['result:overview']);
    expect(audit.citations[0]).toMatchObject({
      toolMatchesDefinition: false,
      issues: ['mismatch'],
    });
  });
});
