/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */
//
// Task 16.7 — streaming/error behaviors on a streaming screen (the Playground):
//   - submit targets the configured base URL (2.4)
//   - chunk append rendering (2.5)
//   - streaming-error replacement + action identification (2.6)
//   - backend-error message + input retention (2.7)
//   - timeout/connection error + input retention (2.8)
//   - loading-indicator lifecycle (2.10)

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import React from 'react';

const PLAYGROUND_URL = 'http://localhost:8001';

function streamFromStrings(parts: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < parts.length) {
        controller.enqueue(encoder.encode(parts[i]));
        i += 1;
      } else {
        controller.close();
      }
    },
  });
}

function okSSE(parts: string[]): Response {
  return { ok: true, status: 200, body: streamFromStrings(parts), text: async () => '' } as unknown as Response;
}

async function loadScreen() {
  vi.stubEnv('VITE_PLAYGROUND_URL', PLAYGROUND_URL);
  const mod = await import('./PlaygroundScreen');
  return mod.PlaygroundScreen;
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

function typePrompt(text: string) {
  const promptBox = document.getElementById('main-prompt-textarea-id') as HTMLTextAreaElement;
  fireEvent.change(promptBox, { target: { value: text } });
  return promptBox;
}

function clickRun() {
  fireEvent.click(screen.getByText(/Compile & Run Gateway Stream/i));
}

describe('Playground streaming (Requirements 2.4, 2.5, 2.10)', () => {
  it('submits to the configured base URL and appends streamed chunks', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      okSSE([
        'event: data\ndata: {"text":"Hello "}\n\n',
        'event: data\ndata: {"text":"world"}\n\n',
        'event: done\ndata: {"usage":{"prompt_tokens":1,"output_tokens":2,"total_tokens":3},"persistence":{"ok":true}}\n\n',
      ]),
    );
    vi.stubGlobal('fetch', fetchMock);

    const Playground = await loadScreen();
    render(<Playground onAddHistory={vi.fn()} />);

    typePrompt('hi there');
    clickRun();

    await waitFor(() => expect(screen.getByText(/Hello world/)).toBeInTheDocument());

    // Submit targeted the configured base URL (Requirement 2.4).
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${PLAYGROUND_URL}/generate`);
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body);
    expect(body.prompt).toBe('hi there');
    // Default model corrected to claude-opus-4.7 (Requirement 3.4).
    expect(body.model).toBe('claude-opus-4.7');

    // Token usage rendered on done (Requirement 4.6 surface).
    await waitFor(() => expect(screen.getByText(/total/i)).toBeInTheDocument());
  });

  it('shows a loading indicator after submit and removes it on completion (2.10)', async () => {
    // A controllable stream: emits one chunk, then we close it.
    let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null;
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controllerRef = controller;
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, body, text: async () => '' } as unknown as Response));

    const Playground = await loadScreen();
    render(<Playground onAddHistory={vi.fn()} />);

    typePrompt('loading test');
    clickRun();

    // Loading indicator appears.
    await waitFor(() => expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument());

    // Emit a chunk then finish.
    await act(async () => {
      controllerRef!.enqueue(encoder.encode('event: data\ndata: {"text":"done-chunk"}\n\n'));
      controllerRef!.enqueue(encoder.encode('event: done\ndata: {}\n\n'));
      controllerRef!.close();
    });

    // Loading indicator removed once the request completes.
    await waitFor(() => expect(screen.queryByRole('status', { name: /loading/i })).not.toBeInTheDocument());
    expect(screen.getByText(/done-chunk/)).toBeInTheDocument();
  });
});

describe('Playground error handling (Requirements 2.6, 2.7)', () => {
  it('replaces partial content with a terminal streaming error naming the action (2.6)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      okSSE([
        'event: data\ndata: {"text":"partial answer"}\n\n',
        'event: error\ndata: {"action":"playground_generate","reason":"gateway exploded mid-stream"}\n\n',
      ]),
    );
    vi.stubGlobal('fetch', fetchMock);

    const Playground = await loadScreen();
    render(<Playground onAddHistory={vi.fn()} />);

    typePrompt('trigger error');
    clickRun();

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    // The error names the failed action and reason.
    expect(screen.getByText(/Playground Generate Failed/i)).toBeInTheDocument();
    expect(screen.getByText(/gateway exploded mid-stream/i)).toBeInTheDocument();
  });

  it('shows a backend non-2xx error and retains the submitted prompt (2.7)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 502, body: null, text: async () => 'bad gateway' } as unknown as Response),
    );

    const Playground = await loadScreen();
    render(<Playground onAddHistory={vi.fn()} />);

    const promptBox = typePrompt('keep me after failure');
    clickRun();

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    // Input retained (Requirement 2.7).
    expect(promptBox.value).toBe('keep me after failure');
    expect(screen.getByText(/502/)).toBeInTheDocument();
  });
});

describe('Playground timeout (Requirement 2.8)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('surfaces a connection timeout after 60s and retains the input', async () => {
    // fetch hangs until aborted by the 60s timeout.
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

    const Playground = await loadScreen();
    render(<Playground onAddHistory={vi.fn()} />);

    const promptBox = typePrompt('retain on timeout');
    clickRun();

    // Drive the 60s AbortController timeout. Flushing microtasks via the async
    // timer advance propagates the abort rejection and the resulting state update
    // (no waitFor — RTL's poller would deadlock under fake timers).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_001);
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/Connection Timeout Failed/i)).toBeInTheDocument();
    expect(screen.getByText(/60 seconds/i)).toBeInTheDocument();
    // Input retained (Requirement 2.8).
    expect(promptBox.value).toBe('retain on timeout');
  });
});
