/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */
//
// Task 16.7 — navigation + screen selection (Requirements 2.2, 2.3).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import React from 'react';

const SIX_NAMES = [
  'LLM Playground',
  'Support Chatbot',
  'Ask the Web',
  'Deep Research',
  'Image Service',
  'Capstone Agent',
];

async function loadApp() {
  // Configure all six backends so the dashboard advisory is absent.
  vi.stubEnv('VITE_PLAYGROUND_URL', 'http://localhost:8001');
  vi.stubEnv('VITE_SUPPORT_URL', 'http://localhost:8002');
  vi.stubEnv('VITE_WEBAGENT_URL', 'http://localhost:8003');
  vi.stubEnv('VITE_DEEPRESEARCH_URL', 'http://localhost:8004');
  vi.stubEnv('VITE_IMAGE_URL', 'http://localhost:8005');
  vi.stubEnv('VITE_CAPSTONE_URL', 'http://localhost:8006');
  const mod = await import('./../App');
  return mod.default;
}

beforeEach(() => {
  vi.resetModules();
  // No chat session calls fire unless we navigate to support and submit.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ session_id: 's1' }) } as unknown as Response));
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('navigation surface (Requirements 2.2, 2.3)', () => {
  it('renders exactly six named mini-project entries', async () => {
    const App = await loadApp();
    render(<App />);

    const nav = screen.getByRole('navigation');
    for (const name of SIX_NAMES) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
    // The sidebar nav contains exactly six project buttons + the Dashboard entry.
    const navButtons = nav.querySelectorAll('button');
    // 6 projects + 1 dashboard = 7 nav buttons.
    expect(navButtons.length).toBe(7);
  });

  it('renders the matching screen when a project is selected', async () => {
    const App = await loadApp();
    render(<App />);

    // Dashboard initially.
    expect(screen.getByText('AI Engineer Practice Monorepo')).toBeInTheDocument();

    // Select the playground from the sidebar.
    const nav = screen.getByRole('navigation');
    const playgroundBtn = Array.from(nav.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('LLM Playground'),
    )!;
    fireEvent.click(playgroundBtn);

    // The playground screen exposes its run button.
    expect(screen.getByText(/Compile & Run Gateway Stream/i)).toBeInTheDocument();

    // Switch to the image screen.
    const imageBtn = Array.from(nav.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Image Service'),
    )!;
    fireEvent.click(imageBtn);
    expect(screen.getByText(/Generate Design Frame/i)).toBeInTheDocument();
  });
});
