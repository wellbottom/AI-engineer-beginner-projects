import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
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
      animation: {
        'caret-blink': 'blink 1s step-end infinite',
        pulse: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        blink: {
          'from, to': { opacity: '1' },
          '50%': { opacity: '0' },
        },
      },
    },
  },
  plugins: [],
};

export default config;
