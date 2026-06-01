import type { Config } from 'tailwindcss';
import { baseTheme } from '@repo/ts-config/tailwind';

// apps/web consumes the shared Tailwind base (design tokens mapped to the CSS
// variables in src/index.css) from @repo/ts-config and supplies its own content
// globs plus the app-specific animation/keyframes extensions.
const config: Config = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      ...baseTheme.extend,
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
