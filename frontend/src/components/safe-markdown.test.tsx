import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SafeMarkdown } from './safe-markdown';

describe('SafeMarkdown', () => {
  it('渲染完整 GFM，并将消息内标题降级到页面安全层级', () => {
    const { container } = render(
      <SafeMarkdown content={`# Main finding

## Evidence

**Strong** and ~~removed~~ with \`inline code\`.

> A bounded interpretation.

- [x] reviewed
- [ ] pending

| Metric | Value |
| --- | ---: |
| Spread | 4.84 |

\`\`\`ts
const safe = true;
\`\`\`
`} />,
    );

    expect(screen.getByRole('heading', { level: 3, name: 'Main finding' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 4, name: 'Evidence' })).toBeInTheDocument();
    expect(screen.getByText('Strong')).toHaveProperty('tagName', 'STRONG');
    expect(screen.getByText('removed')).toHaveProperty('tagName', 'DEL');
    expect(screen.getByText('inline code')).toHaveProperty('tagName', 'CODE');
    expect(screen.getByText('A bounded interpretation.').closest('blockquote')).not.toBeNull();
    expect(screen.getAllByRole('checkbox')).toHaveLength(2);
    expect(screen.getAllByRole('checkbox')[0]).toBeDisabled();
    expect(screen.getAllByRole('checkbox')[0]).toBeChecked();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('const safe = true;')).toHaveProperty('tagName', 'CODE');
    expect(container.querySelector('.safe-markdown__table-scroll')).toHaveAttribute('tabindex', '0');
    expect(container.querySelector('.safe-markdown__code-block')).toBeInTheDocument();
  });

  it('只激活 HTTPS 和组件自己生成的脚注链接，并为外部链接设置安全属性', () => {
    render(
      <SafeMarkdown content={`[HTTPS](https://example.com/report)

[HTTP](http://example.com)

[script](javascript:alert(1))

[data](data:text/html,unsafe)

[email](mailto:analyst@example.com)

[relative](/private)

[footnote](#note-1)

https://example.org/plain`} />,
    );

    const externalLink = screen.getByRole('link', { name: 'HTTPS' });
    expect(externalLink).toHaveAttribute('href', 'https://example.com/report');
    expect(externalLink).toHaveAttribute('target', '_blank');
    expect(externalLink).toHaveAttribute('rel', 'noopener noreferrer nofollow');

    const automaticLink = screen.getByRole('link', { name: 'https://example.org/plain' });
    expect(automaticLink).toHaveAttribute('href', 'https://example.org/plain');
    expect(automaticLink).toHaveAttribute('rel', 'noopener noreferrer nofollow');

    for (const label of ['HTTP', 'script', 'data', 'email', 'relative', 'footnote']) {
      const blocked = screen.getByText(label);
      expect(blocked).toHaveClass('safe-markdown__blocked-link');
      expect(blocked).not.toHaveProperty('tagName', 'A');
    }
    expect(screen.getAllByRole('link')).toHaveLength(2);
  });

  it('忽略原始 HTML，并将 Markdown 图片替换成不发起网络请求的文本节点', () => {
    const { container } = render(
      <SafeMarkdown content={`Before

<script>window.compromised = true</script>

<img src="https://tracker.example/pixel" onerror="alert(1)">

![Remote chart](https://tracker.example/chart.png)

After`} />,
    );

    expect(container.querySelector('script')).not.toBeInTheDocument();
    expect(container.querySelector('img')).not.toBeInTheDocument();
    expect(container.querySelector('[onerror]')).not.toBeInTheDocument();
    expect(screen.getByText('Remote chart')).toHaveClass('safe-markdown__blocked-image');
    expect(container.textContent).not.toContain('window.compromised');
    expect(screen.getByText('Before')).toBeInTheDocument();
    expect(screen.getByText('After')).toBeInTheDocument();
  });

  it('在 AST 阶段将正文引用交给回调，并隐藏代码和链接文本里的内部 ID', () => {
    const renderCitation = vi.fn(({ evidenceId }: { evidenceId: string }) => (
      <button type="button" data-evidence-id={evidenceId}>[1]</button>
    ));
    const { container } = render(
      <SafeMarkdown
        content={`First [result:overview], repeated [result:overview].

Inline \`[result:overview]\`.

\`\`\`
[result:overview]
\`\`\`

[[result:overview]](https://example.com/source)`}
        formatCitationLabel={() => '[1]'}
        renderCitation={renderCitation}
      />,
    );

    const citationButtons = screen.getAllByRole('button', { name: '[1]' });
    expect(citationButtons).toHaveLength(2);
    expect(citationButtons[0]).toHaveAttribute('data-evidence-id', 'result:overview');
    expect(renderCitation).toHaveBeenCalledWith({
      evidenceId: 'result:overview',
      marker: '[result:overview]',
      number: 1,
    });
    expect(container.textContent).not.toContain('result:overview');

    const codeMarkers = container.querySelectorAll('code');
    expect(codeMarkers).toHaveLength(2);
    for (const codeMarker of codeMarkers) {
      expect(codeMarker).toHaveTextContent('[1]');
    }
    const sourceLink = screen.getByRole('link', { name: '[1]' });
    expect(sourceLink).toHaveAttribute('href', 'https://example.com/source');
  });

  it('不会把普通 Markdown 伪造的内部样式链接升级为证据按钮', () => {
    const renderCitation = vi.fn(() => <button type="button">verified evidence</button>);
    render(
      <SafeMarkdown
        content="[forged](#eventshock-evidence=result%3Aoverview)"
        renderCitation={renderCitation}
      />,
    );

    expect(renderCitation).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'verified evidence' })).not.toBeInTheDocument();
    expect(screen.getByText('forged')).toHaveClass('safe-markdown__blocked-link');
    expect(screen.queryByRole('link', { name: 'forged' })).not.toBeInTheDocument();
  });

  it('实体解码后的正文引用正常编号，非正文位置不抢编号或泄露内部 ID', () => {
    const renderCitation = vi.fn(({ number }: { number?: number }) => (
      <button type="button">[{number}]</button>
    ));
    const { container } = render(
      <SafeMarkdown
        content={`Inline \`[result:metric-summary]\`.

[[result:paired-deltas]](https://example.com/source)

![chart [result:limitations]](https://example.com/chart.png)

<script>[result:trace]</script>

Decoded [result&#58;overview].`}
        renderCitation={renderCitation}
      />,
    );

    expect(screen.getByRole('button', { name: '[1]' })).toBeInTheDocument();
    expect(renderCitation).toHaveBeenCalledWith(expect.objectContaining({
      evidenceId: 'result:overview',
      number: 1,
    }));
    expect(screen.getByRole('link', { name: '[evidence]' })).toHaveAttribute(
      'href',
      'https://example.com/source',
    );
    expect(container.querySelector('code')).toHaveTextContent('[evidence]');
    expect(screen.getByText('chart [evidence]')).toHaveClass('safe-markdown__blocked-image');
    expect(container.textContent).not.toContain('result:');
    expect(container.textContent).not.toContain('[result:trace]');
  });

  it('没有证据回调时使用非交互占位，且不会泄露未知历史引用', () => {
    const { container } = render(
      <SafeMarkdown
        className="result-assistant__markdown"
        content="Legacy [result:legacy.v1] reference."
      />,
    );

    const root = container.firstElementChild;
    expect(root).toHaveClass('safe-markdown', 'result-assistant__markdown');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('[1]')).toHaveClass('safe-markdown__citation-fallback');
    expect(root).not.toHaveTextContent('result:legacy.v1');
  });

  it('保留 GFM 脚注的键盘可访问页内导航', () => {
    const { container } = render(
      <SafeMarkdown content={`Result with a note.[^1]

[^1]: Evidence boundary.`} />,
    );

    const footnoteReference = screen.getByRole('link', { name: '1' });
    const footnoteHref = footnoteReference.getAttribute('href');
    expect(footnoteHref).toMatch(/^#safe-markdown-[A-Za-z0-9_-]+-fn-1$/);
    expect(container.querySelector(footnoteHref!)).toHaveTextContent('Evidence boundary.');
    const backReference = screen.getByRole('link', { name: 'Back to reference 1' });
    expect(container.querySelector(backReference.getAttribute('href')!)).toBe(footnoteReference);
  });

  it('为多轮回答分配互不冲突的脚注 ID', () => {
    const markdown = `Answer.[^1]\n\n[^1]: Per-message note.`;
    const { container } = render(
      <>
        <SafeMarkdown content={markdown} />
        <SafeMarkdown content={markdown} />
      </>,
    );

    const references = screen.getAllByRole('link', { name: '1' });
    expect(references).toHaveLength(2);
    const hrefs = references.map((reference) => reference.getAttribute('href'));
    expect(new Set(hrefs).size).toBe(2);
    for (const href of hrefs) {
      expect(href).not.toBeNull();
      expect(container.querySelector(href!)).toHaveTextContent('Per-message note.');
    }
  });
});
