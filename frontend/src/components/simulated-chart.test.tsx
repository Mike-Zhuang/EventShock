import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SimulatedChart } from './simulated-chart';

describe('SimulatedChart', () => {
  it('以固定可见标签和不可读水印标记程序生成图表', () => {
    render(
      <SimulatedChart label="SIMULATED DATA">
        <div role="img" aria-label="paired comparison">chart</div>
      </SimulatedChart>,
    );

    expect(screen.getByTestId('simulated-chart')).toContainElement(
      screen.getByRole('img', { name: 'paired comparison' }),
    );
    const labels = screen.getAllByText('SIMULATED DATA');
    expect(labels).toHaveLength(2);
    expect(labels[1]).toHaveAttribute('aria-hidden', 'true');
  });
});
