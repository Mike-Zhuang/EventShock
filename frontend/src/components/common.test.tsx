import { NumberInput, Select, SelectItem, TextInput } from '@carbon/react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { I18nProvider } from '../i18n';
import { ParameterHelp } from './common';

describe('ParameterHelp', () => {
  it('把帮助按钮放在 Carbon decorator 中，而不是嵌入原生表单标签', () => {
    render(
      <I18nProvider>
        <TextInput
          id="model-name"
          labelText="Model"
          decorator={<ParameterHelp label="Model" explanation="Model help" />}
        />
        <NumberInput
          id="seed-count"
          label="Seed count"
          decorator={<ParameterHelp label="Seed count" explanation="Seed help" />}
        />
        <Select
          id="network-type"
          labelText="Network type"
          decorator={<ParameterHelp label="Network type" explanation="Network help" />}
        >
          <SelectItem value="small-world" text="Small world" />
        </Select>
      </I18nProvider>,
    );

    expect(screen.getByRole('textbox', { name: 'Model' })).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: 'Seed count' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Network type' })).toBeInTheDocument();
    expect(document.querySelectorAll('label button')).toHaveLength(0);

    for (const label of ['Model', 'Seed count', 'Network type']) {
      const trigger = screen.getByRole('button', { name: `View parameter help for ${label}` });
      expect(trigger).toHaveAttribute('aria-describedby');
      expect(document.getElementById(trigger.getAttribute('aria-describedby') ?? '')).not.toBeNull();
    }
  });
});
