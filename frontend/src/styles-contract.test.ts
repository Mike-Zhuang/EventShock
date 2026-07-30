import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const styles = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8');
const carbonEntry = readFileSync(resolve(process.cwd(), 'src/carbon.scss'), 'utf8');

describe('通用界面样式契约', () => {
  it('桌面和移动导航占满分组，并在短窗口中保留独立滚动与焦点余量', () => {
    expect(styles).toMatch(
      /\.sidebar nav,\s*\.mobile-navigation nav\s*\{[^}]*min-height:\s*0;[^}]*flex:\s*1 1 auto;[^}]*overflow-y:\s*auto;/s,
    );
    expect(styles).toMatch(
      /\.sidebar nav button,\s*\.mobile-navigation nav button\s*\{[^}]*width:\s*100%;/s,
    );
    expect(styles).toMatch(
      /\.sidebar nav button:focus-visible,\s*\.mobile-navigation nav button:focus-visible\s*\{[^}]*scroll-margin-block:\s*8px;/s,
    );
    expect(styles).toMatch(
      /\.sidebar__footer\s*\{[^}]*flex:\s*0 0 auto;/s,
    );
  });

  it('卡片、通知、进度、运行详情和状态面板复用桌面与移动内边距 token', () => {
    expect(styles).toContain('--card-padding: 24px;');
    expect(styles).toContain('--card-padding-compact: 20px;');
    expect(styles).toMatch(
      /@media \(max-width:\s*720px\)\s*\{\s*:root\s*\{[^}]*--card-padding:\s*16px;[^}]*--card-padding-compact:\s*16px;/s,
    );
    expect(styles).toMatch(/\.state-panel\s*\{[^}]*padding:\s*var\(--card-padding\);/s);
    expect(styles).toMatch(/\.run-detail\s*\{[^}]*padding:\s*var\(--card-padding\);/s);
    expect(styles).toMatch(
      /\.cognition-runtime-progress\s*\{[^}]*padding:\s*var\(--card-padding-compact\);/s,
    );
    expect(styles).toMatch(
      /\.cds--inline-notification__text-wrapper\s*\{[^}]*padding-block:\s*var\(--card-padding-compact\);/s,
    );
  });

  it('中文排版单独校准，技术值可换行，中文操作按钮不继承过宽英文假设', () => {
    expect(styles).toMatch(
      /:lang\(zh-CN\) \.page-header h1\s*\{[^}]*letter-spacing:\s*-0\.02em;[^}]*line-height:\s*1\.16;/s,
    );
    expect(styles).toMatch(
      /:lang\(zh-CN\) \.page-header p,[\s\S]*?:lang\(zh-CN\) \.state-panel p\s*\{[^}]*max-width:\s*46em;[^}]*line-height:\s*1\.65;/s,
    );
    expect(styles).toMatch(
      /:lang\(zh-CN\) \.page-header__actions > \.cds--btn,[\s\S]*?\{[^}]*width:\s*auto;[^}]*max-width:\s*18rem;/s,
    );
    expect(styles).toMatch(
      /\.definition-list dd,\s*\[data-technical-value\]\s*\{[^}]*overflow-wrap:\s*anywhere;[^}]*word-break:\s*break-word;/s,
    );
  });

  it('生产样式禁用 Carbon 外部字体，并为中文保留系统字体回退', () => {
    expect(carbonEntry).toContain('$css--font-face: false');
    expect(styles).not.toContain('1.www.s81c.com');
    expect(styles).toContain("'PingFang SC'");
    expect(styles).toContain("'Noto Sans CJK SC'");
    expect(styles).toContain("'Microsoft YaHei'");
  });
});
