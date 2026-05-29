import type { Config } from 'tailwindcss';

/**
 * Shared Tailwind base configuration for the monorepo.
 *
 * Apps (e.g. apps/web) extend this by spreading `baseTheme` into their own
 * `theme.extend` and supplying their own `content` globs. The design tokens
 * below map to CSS variables defined in the app's `index.css`
 * (see docs/ui-design.md for the canonical token values).
 */
export const baseTheme: NonNullable<Config['theme']> = {
  extend: {
    colors: {
      bg: 'var(--bg)',
      surface: 'var(--surface)',
      'surface-2': 'var(--surface-2)',
      'surface-3': 'var(--surface-3)',
      'border-dim': 'var(--border)',
      'border-strong': 'var(--border-strong)',
      'text-main': 'var(--text)',
      'text-muted': 'var(--text-muted)',
      'text-faint': 'var(--text-faint)',
      'primary-main': 'var(--primary)',
      'primary-hover': 'var(--primary-hover)',
      'primary-contrast': 'var(--primary-contrast)',
      'accent-subtle': 'var(--accent)',
      'warning-subtle': 'var(--warning)',
      'danger-subtle': 'var(--danger)',
      'danger-bg': 'var(--danger-bg)',
    },
    fontFamily: {
      sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
    },
    borderRadius: {
      sm: 'var(--r-sm)',
      md: 'var(--r-md)',
      lg: 'var(--r-lg)',
    },
  },
};

/**
 * A minimal, ready-to-extend base config. Apps should override `content`.
 */
const baseConfig: Omit<Config, 'content'> = {
  theme: baseTheme,
  plugins: [],
};

export default baseConfig;
