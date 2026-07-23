import { useId, type ReactNode } from 'react';
import ReactMarkdown, { type Components, type UrlTransform } from 'react-markdown';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import type { Element } from 'hast';
import type { Link, Parent, PhrasingContent, Root, Text } from 'mdast';
import {
  buildResultEvidenceNumbering,
  splitResultEvidenceText,
  type ResultEvidenceNumbering,
} from './result-evidence';

const EVIDENCE_ID_PATTERN = /^result:[A-Za-z0-9][A-Za-z0-9._:-]{0,72}$/;
const BLOCKED_NESTED_LINK_NODE_TYPES = new Set(['link', 'linkReference']);

const SAFE_MARKDOWN_SCHEMA = {
  ...defaultSchema,
  // remark 使用每个组件实例独有的安全前缀；再次前缀化会破坏脚注正反向链接。
  clobberPrefix: '',
  protocols: {
    ...defaultSchema.protocols,
    href: ['https'],
  },
  attributes: {
    ...defaultSchema.attributes,
    a: [
      ...(defaultSchema.attributes?.a ?? []),
      'dataEvidenceId',
    ],
  },
};

export interface SafeMarkdownCitation {
  evidenceId: string;
  marker: string;
  number?: number;
}

export interface SafeMarkdownProps {
  content: string;
  className?: string;
  citationNumbering?: ResultEvidenceNumbering;
  renderCitation?: (citation: SafeMarkdownCitation) => ReactNode;
  formatCitationLabel?: (citation: SafeMarkdownCitation) => string;
}

interface EvidencePluginOptions {
  citationNumbering: ResultEvidenceNumbering;
  formatCitationLabel?: (citation: SafeMarkdownCitation) => string;
}

function citationFromEvidenceId(
  evidenceId: string,
  citationNumbering: ResultEvidenceNumbering,
): SafeMarkdownCitation {
  return {
    evidenceId,
    marker: `[${evidenceId}]`,
    number: citationNumbering.numberByEvidenceId.get(evidenceId),
  };
}

function formatCitationFallback(
  citation: SafeMarkdownCitation,
  formatCitationLabel?: EvidencePluginOptions['formatCitationLabel'],
): string {
  return formatCitationLabel?.(citation)
    ?? (citation.number === undefined ? '[evidence]' : `[${citation.number}]`);
}

function evidenceIdFromNode(node: Element | undefined): string | null {
  const evidenceId = node?.properties?.dataEvidenceId;
  return typeof evidenceId === 'string' && EVIDENCE_ID_PATTERN.test(evidenceId)
    ? evidenceId
    : null;
}

function replaceReferencesWithText(
  value: string,
  citationNumbering: ResultEvidenceNumbering,
  formatCitationLabel?: EvidencePluginOptions['formatCitationLabel'],
): string {
  return splitResultEvidenceText(value, citationNumbering).map((segment) => {
    if (segment.kind === 'text' || !segment.evidenceId) {
      return segment.value;
    }
    return formatCitationFallback(
      citationFromEvidenceId(segment.evidenceId, citationNumbering),
      formatCitationLabel,
    );
  }).join('');
}

function splitEvidenceText(
  node: Text,
  citationNumbering: ResultEvidenceNumbering,
  formatCitationLabel?: EvidencePluginOptions['formatCitationLabel'],
): PhrasingContent[] {
  const replacements: PhrasingContent[] = [];
  const segments = splitResultEvidenceText(node.value, citationNumbering);

  for (const segment of segments) {
    if (segment.kind === 'text' || !segment.evidenceId) {
      replacements.push({ type: 'text', value: segment.value });
      continue;
    }
    const citation = citationFromEvidenceId(segment.evidenceId, citationNumbering);
    if (citation.number === undefined) {
      replacements.push({
        type: 'text',
        value: formatCitationFallback(citation, formatCitationLabel),
      });
      continue;
    }
    const citationLink: Link = {
      type: 'link',
      url: '#',
      // 普通 Markdown 无法创建该 AST 属性；仅本插件可把服务器验证过的引用升级为按钮。
      data: {
        hProperties: {
          dataEvidenceId: segment.evidenceId,
        },
      },
      children: [{
        type: 'text',
        value: formatCitationLabel?.(citation) ?? segment.value,
      }],
    };
    replacements.push(citationLink);
  }
  return replacements;
}

function sanitizeLegacyReferenceText(
  parent: Parent,
  citationNumbering: ResultEvidenceNumbering,
  formatCitationLabel?: EvidencePluginOptions['formatCitationLabel'],
): void {
  for (const child of parent.children) {
    if ((child.type === 'image' || child.type === 'imageReference') && child.alt) {
      child.alt = replaceReferencesWithText(
        child.alt,
        citationNumbering,
        formatCitationLabel,
      );
      continue;
    }
    if (child.type === 'code' || child.type === 'inlineCode') {
      child.value = replaceReferencesWithText(
        child.value,
        citationNumbering,
        formatCitationLabel,
      );
      continue;
    }
    if ('children' in child && Array.isArray(child.children)) {
      sanitizeLegacyReferenceText(child as Parent, citationNumbering, formatCitationLabel);
    }
  }
}

function replaceEvidenceTextNodes(
  parent: Parent,
  citationNumbering: ResultEvidenceNumbering,
  formatCitationLabel?: EvidencePluginOptions['formatCitationLabel'],
  insideLink = false,
): void {
  const nextChildren: Parent['children'] = [];

  for (const child of parent.children) {
    if (child.type === 'text') {
      if (insideLink) {
        nextChildren.push({
          ...child,
          value: replaceReferencesWithText(
            child.value,
            citationNumbering,
            formatCitationLabel,
          ),
        });
      } else {
        nextChildren.push(...splitEvidenceText(
          child,
          citationNumbering,
          formatCitationLabel,
        ));
      }
      continue;
    }

    if ('children' in child && Array.isArray(child.children)) {
      const childIsLink = insideLink || BLOCKED_NESTED_LINK_NODE_TYPES.has(child.type);
      replaceEvidenceTextNodes(
        child as Parent,
        citationNumbering,
        formatCitationLabel,
        childIsLink,
      );
    }
    nextChildren.push(child);
  }

  parent.children = nextChildren;
}

/**
 * 在 Markdown AST 层识别证据引用，避免对生成后的 HTML 做字符串替换。
 * 旧历史回答若把引用放进代码或链接文本，只显示安全标签而不泄露内部 ID。
 */
export function remarkEvidenceCitations(options: EvidencePluginOptions) {
  return (tree: Root): void => {
    sanitizeLegacyReferenceText(
      tree,
      options.citationNumbering,
      options.formatCitationLabel,
    );
    replaceEvidenceTextNodes(
      tree,
      options.citationNumbering,
      options.formatCitationLabel,
    );
  };
}

function createSafeUrlTransform(footnotePrefix: string): UrlTransform {
  return (url) => {
    // 只允许该 Markdown 实例自己生成的脚注锚点，避免回答借任意 hash 控制 SPA 路由。
    if (url.startsWith(`#${footnotePrefix}`)) return url;
    if (!/^https:\/\//i.test(url)) return null;
    try {
      return new URL(url).protocol === 'https:' ? url : null;
    } catch {
      return null;
    }
  };
}

function markdownComponents(
  citationNumbering: ResultEvidenceNumbering,
  renderCitation: SafeMarkdownProps['renderCitation'],
  formatCitationLabel: SafeMarkdownProps['formatCitationLabel'],
): Components {
  return {
    a: ({ node, href, children, ...props }) => {
      const evidenceId = evidenceIdFromNode(node);
      if (evidenceId !== null) {
        const citation = citationFromEvidenceId(evidenceId, citationNumbering);
        return renderCitation
          ? <>{renderCitation(citation)}</>
          : (
            <span className="safe-markdown__citation-fallback">
              {formatCitationFallback(citation, formatCitationLabel)}
            </span>
          );
      }
      if (!href) {
        return <span className="safe-markdown__blocked-link">{children}</span>;
      }
      if (href.startsWith('#')) {
        return <a {...props} href={href}>{children}</a>;
      }
      return (
        <a
          {...props}
          href={href}
          rel="noopener noreferrer nofollow"
          target="_blank"
        >
          {children}
        </a>
      );
    },
    img: ({ node: _node, alt }) => (
      <span className="safe-markdown__blocked-image" role="note">
        {alt ?? ''}
      </span>
    ),
    h1: ({ node: _node, ...props }) => <h3 {...props} />,
    h2: ({ node: _node, ...props }) => <h4 {...props} />,
    h3: ({ node: _node, ...props }) => <h5 {...props} />,
    h4: ({ node: _node, ...props }) => <h6 {...props} />,
    h5: ({ node: _node, ...props }) => <h6 {...props} />,
    h6: ({ node: _node, ...props }) => <h6 {...props} />,
    table: ({ node: _node, ...props }) => (
      <div className="safe-markdown__table-scroll" tabIndex={0}>
        <table {...props} />
      </div>
    ),
    pre: ({ node: _node, ...props }) => (
      <pre className="safe-markdown__code-block" {...props} />
    ),
  };
}

export function SafeMarkdown({
  content,
  className,
  citationNumbering,
  renderCitation,
  formatCitationLabel,
}: SafeMarkdownProps) {
  const rootClassName = ['safe-markdown', className].filter(Boolean).join(' ');
  const effectiveCitationNumbering = citationNumbering
    ?? buildResultEvidenceNumbering(content);
  const footnotePrefix = `safe-markdown-${useId().replace(/[^A-Za-z0-9_-]/g, '')}-`;

  return (
    <div className={rootClassName}>
      <ReactMarkdown
        components={markdownComponents(
          effectiveCitationNumbering,
          renderCitation,
          formatCitationLabel,
        )}
        rehypePlugins={[[rehypeSanitize, SAFE_MARKDOWN_SCHEMA]]}
        remarkRehypeOptions={{ clobberPrefix: footnotePrefix }}
        remarkPlugins={[
          remarkGfm,
          [remarkEvidenceCitations, {
            citationNumbering: effectiveCitationNumbering,
            formatCitationLabel,
          }],
        ]}
        skipHtml
        urlTransform={createSafeUrlTransform(footnotePrefix)}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
