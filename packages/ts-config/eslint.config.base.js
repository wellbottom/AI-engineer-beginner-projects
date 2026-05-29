// Shared ESLint flat-config base for the monorepo.
//
// Apps (e.g. apps/web) import this array and append their own
// framework-specific configs (React, Vite, etc.). Kept dependency-free here
// so it stays a valid, extendable stub until apps wire in their plugins.

/** @type {import("eslint").Linter.Config[]} */
export const baseConfig = [
  {
    ignores: ['**/dist/**', '**/node_modules/**', '**/.vite/**', '**/coverage/**'],
  },
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
    },
    linterOptions: {
      reportUnusedDisableDirectives: true,
    },
    rules: {
      'no-unused-vars': 'warn',
      'no-undef': 'off',
    },
  },
];

export default baseConfig;
