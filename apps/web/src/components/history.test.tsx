/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */
//
// Task 16.8 — history browsing (Requirements 13.1, 13.2, 13.4, 13.5, 13.6).
//   - list renders each persisted record with its timestamp (13.1, 13.2)
//   - selecting a record renders its full inputs/outputs detail (13.4)
//   - empty list shows the empty-history indication (13.5)
//   - a stubbed failure or 60s timeout shows an error identifying the failed
//     history retrieval + affected project (13.6, fake timers)

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import React from 'react';

const PLAYGROUND_URL = 'http://localhost:8001';

const RECORDS = [
  {
    id: 'rec-1',
    projectId: 'playground',
    created_at: '2026-02-01T10:00:00.000Z',
    label: 'first prompt',
    inputs: { prompt: 'first prompt', model: 'claude-opus-4.7', temperature: 0.5, max_tokens: 256 },
    outputs: { text: 'first answer', metadata: { usage: { prompt_tokens: 1, output_tokens: 1, total_tokens: 2 } } },
  },
  {
    id: 'rec-2',
    projectId: 'playground',
    created_at: '2026-02-02T12:30:00.000Z',
    label: 'second prompt',
    inputs: { prompt: 'second prompt', model: 'claude-opus-4.7' },
    outputs: { text: 'second answer' },
  },
];

async function loadApp() {
  vi.stubEnv('VITE_PLAYGROUND_URL', PLAYGROUND_URL);
  vi.stubEnv('VITE_SUPPORT_URL', 'http://localhost:8002');
  vi.stubEnv('VITE_WEBAGENT_URL', 'http://localhost:8003');
  vi.stubEnv('VITE_DEEPRESEARCH_URL', 'http://localhost:8004');
  vi.stubEnv('VITE_IMAGE_URL', 'http://localhost:8005');
  vi.stubEnv('VITE_CAPSTONE_URL', 'http://localhost:8006');
  const mod = await import('./../App');
  return mod.default;
}

function gotoPlaygroundHistory() {
  // Sidebar -> LLM Playground.
  const nav = screen.getByRole('navigation');
  const playgroundBtn = Array.from(nav.querySelectorAll('button')).find((b) =>
    b.textContent?.includes('LLM Playground'),
  )!;
  fireEvent.click(playgroundBtn);
  // Topbar -> History toggle.
  fireEvent.click(screen.getByTitle(/historic execution logs/i));
}

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.resetModules();
});

describe('history list + detail (Requirements 13.1, 13.2, 13.4)', () => {
  it('lists each persisted record with its timestamp from the backend', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => RECORDS } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    const App = await loadApp();
    render(<App />);
    gotoPlaygroundHistory();

    await waitFor(() => expect(screen.getByText('first prompt')).toBeInTheDocument());
    expect(screen.getByText('second prompt')).toBeInTheDocument();

    // GET /history against the configured base URL.
    expect(fetchMock).toHaveBeenCalledWith(
      `${PLAYGROUND_URL}/history`,
      expect.objectContaining({ method: 'GET' }),
    );
    // Each record shows its timestamp (locale rendering of created_at).
    const ts1 = new Date(RECORDS[0].created_at).toLocaleString();
    expect(screen.getByText(ts1)).toBeInTheDocument();
  });

  it('renders the full inputs/outputs detail when a record is selected (13.4)', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/history')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => RECORDS } as unknown as Response);
      }
      // GET /history/rec-1 -> full detail
      return Promise.resolve({ ok: true, status: 200, json: async () => RECORDS[0] } as unknown as Response);
    });
    vi.stubGlobal('fetch', fetchMock);

    const App = await loadApp();
    render(<App />);
    gotoPlaygroundHistory();

    await waitFor(() => expect(screen.getByText('first prompt')).toBeInTheDocument());
    fireEvent.click(screen.getByText('first prompt'));

    // Detail view renders the persisted prompt + output.
    await waitFor(() => expect(screen.getByText(/Source Prompt/i)).toBeInTheDocument());
    expect(screen.getByText('first answer')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `${PLAYGROUND_URL}/history/rec-1`,
      expect.objectContaining({ method: 'GET' }),
    );
  });
});

describe('empty history (Requirement 13.5)', () => {
  it('shows the empty-history indication when the backend list is empty', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] } as unknown as Response));

    const App = await loadApp();
    render(<App />);
    gotoPlaygroundHistory();

    await waitFor(() => expect(screen.getByText(/No history captured yet/i)).toBeInTheDocument());
  });
});

describe('history retrieval failure / timeout (Requirement 13.6)', () => {
  it('shows an error identifying the failed history retrieval + affected project on a backend failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({}) } as unknown as Response));

    const App = await loadApp();
    render(<App />);
    gotoPlaygroundHistory();

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    // Names the failed history retrieval and the affected mini-project.
    expect(screen.getByText(/History retrieval failed for LLM Playground/i)).toBeInTheDocument();
  });

  it('shows a 60s-timeout error identifying the retrieval + project (fake timers)', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => {
            const e = new Error('aborted');
            e.name = 'AbortError';
            reject(e);
          });
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const App = await loadApp();
    render(<App />);
    gotoPlaygroundHistory();

    // Drive the 60s history-retrieval timeout; the async timer advance flushes
    // the abort rejection and the resulting error state (no waitFor — RTL's
    // poller would deadlock under fake timers).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_001);
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/History retrieval failed for LLM Playground/i)).toBeInTheDocument();
    expect(screen.getByText(/timed out after 60 seconds/i)).toBeInTheDocument();
  });
});
