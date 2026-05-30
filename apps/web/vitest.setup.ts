// Vitest global setup: register @testing-library/jest-dom matchers and ensure
// the DOM is cleaned up between tests.
import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
});
