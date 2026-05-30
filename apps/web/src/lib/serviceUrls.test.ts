/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */
//
// Task 16.4 — env-sourced VITE_* base URLs (Requirement 2.9).
//
// Verifies getServiceUrl/SERVICE_URLS read the six backend base URLs from
// import.meta.env VITE_* variables (stubbed via Vitest's vi.stubEnv), NOT from
// hardcoded values, and that a non-VITE_-prefixed name resolves to empty (the
// Vite envPrefix guard).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('getServiceUrl / SERVICE_URLS (Requirement 2.9)', () => {
  it('resolves the six VITE_* names from import.meta.env', async () => {
    vi.stubEnv('VITE_PLAYGROUND_URL', 'http://localhost:8001');
    vi.stubEnv('VITE_SUPPORT_URL', 'http://localhost:8002');
    vi.stubEnv('VITE_WEBAGENT_URL', 'http://localhost:8003');
    vi.stubEnv('VITE_DEEPRESEARCH_URL', 'http://localhost:8004');
    vi.stubEnv('VITE_IMAGE_URL', 'http://localhost:8005');
    vi.stubEnv('VITE_CAPSTONE_URL', 'http://localhost:8006');

    // Re-import after stubbing so SERVICE_URLS is computed against the stubs.
    const api = await import('./api');

    expect(api.getServiceUrl('PLAYGROUND_URL')).toBe('http://localhost:8001');
    expect(api.SERVICE_URLS).toEqual({
      playground: 'http://localhost:8001',
      support: 'http://localhost:8002',
      'web-agent': 'http://localhost:8003',
      'deep-research': 'http://localhost:8004',
      image: 'http://localhost:8005',
      capstone: 'http://localhost:8006',
    });
  });

  it('trims whitespace around the configured URL', async () => {
    vi.stubEnv('VITE_PLAYGROUND_URL', '  http://localhost:8001  ');
    const api = await import('./api');
    expect(api.getServiceUrl('PLAYGROUND_URL')).toBe('http://localhost:8001');
  });

  it('resolves a non-VITE_-prefixed name to empty (envPrefix guard)', async () => {
    // Vite never exposes non-VITE_-prefixed vars on import.meta.env. getServiceUrl
    // only reads `VITE_<name>`, so even when NEXT_PUBLIC_*/bare names are present
    // the base URL is empty unless the VITE_-prefixed name is set.
    vi.stubEnv('NEXT_PUBLIC_PLAYGROUND_URL', 'http://should-not-be-used:9999');
    vi.stubEnv('PLAYGROUND_URL', 'http://should-not-be-used:9998');
    const api = await import('./api');

    expect(api.getServiceUrl('PLAYGROUND_URL')).toBe('');
    expect(api.getServiceUrl('NEXT_PUBLIC_PLAYGROUND_URL')).toBe('');
  });

  it('resolves an unset VITE_* name to empty string', async () => {
    const api = await import('./api');
    expect(api.getServiceUrl('DEFINITELY_UNSET_URL')).toBe('');
  });
});
