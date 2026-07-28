import type { ReactNode } from 'react';

interface SimulatedChartProps {
  children: ReactNode;
  label: string;
}

/**
 * 图表标识由界面固定渲染，不依赖模型生成文案，避免截图或局部引用时丢失模拟边界。
 */
export function SimulatedChart({ children, label }: SimulatedChartProps) {
  return (
    <div className="simulated-chart" data-testid="simulated-chart">
      <span className="simulated-chart__badge">{label}</span>
      <span className="simulated-chart__watermark" aria-hidden="true">{label}</span>
      {children}
    </div>
  );
}
