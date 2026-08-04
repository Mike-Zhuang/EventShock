import { Tag } from '@carbon/react';
import { useI18n } from '../i18n';

export function SyntheticInstrumentLabel({
  instrument,
  compact = false,
}: {
  instrument?: string;
  compact?: boolean;
}) {
  const { language } = useI18n();
  const normalizedInstrument = instrument?.trim() || (language === 'zh-CN' ? '未指定' : 'Unspecified');
  const boundary = language === 'zh-CN' ? '合成市场代理' : 'Synthetic market proxy';
  const description = language === 'zh-CN'
    ? `${normalizedInstrument} 只用于合成订单簿与情景机制，不代表真实行情、预测或交易建议。`
    : `${normalizedInstrument} is used only in a synthetic order book and scenario mechanism; it is not real market data, a forecast, or trading advice.`;

  return (
    <span
      className={`synthetic-instrument${compact ? ' synthetic-instrument--compact' : ''}`}
      title={description}
      aria-label={`${normalizedInstrument} · ${boundary}`}
    >
      <code>{normalizedInstrument}</code>
      <Tag type="warm-gray" size="sm" title={description}>{boundary}</Tag>
    </span>
  );
}
