/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */
//
// Task 16.5 — the SSE client uses fetch + ReadableStream, NOT EventSource.
//
// Drives fetchSSEStream with a stubbed fetch returning a ReadableStream of
// event:/data: frames; asserts data/progress/done/error dispatch to the right
// handlers, that EventSource is never constructed, and that the 60s
// AbortController timeout triggers an onError connection failure (fake timers).
// Validates: Requirements 2.5, 2.6, 2.8

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchSSEStream, REQUEST_TIMEOUT_MS } from './api';

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

function okSSEResponse(parts: string[]): Response {
  return {
    ok: true,
    status: 200,
    body: streamFromStrings(parts),
    text: async () => '',
  } as unknown as Response;
}

describe('fetchSSEStream (Requirements 2.5, 2.6, 2.8)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('dispatches data/progress/done/error frames to the right handlers', async () => {
    const frames = [
      'event: data\ndata: {"text":"Hello "}\n\n',
      'event: progress\ndata: {"phase":"search","step":1}\n\n',
      'event: data\ndata: {"text":"world"}\n\n',
      'event: done\ndata: {"usage":{"prompt_tokens":3,"output_tokens":2,"total_tokens":5},"persistence":{"ok":true}}\n\n',
    ];
    const fetchMock = vi.fn().mockResolvedValue(okSSEResponse(frames));
    vi.stubGlobal('fetch', fetchMock);

    const onData = vi.fn();
    const onProgress = vi.fn();
    const onDone = vi.fn();
    const onError = vi.fn();

    await fetchSSEStream('http://backend/generate', { prompt: 'hi' }, {
      onData,
      onProgress,
      onDone,
      onError,
    });

    // Submitted via POST to the configured URL with a JSON body (Requirement 2.4).
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = fetchMock.mock.calls[0];
    expect(calledUrl).toBe('http://backend/generate');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ prompt: 'hi' });

    expect(onData).toHaveBeenCalledTimes(2);
    expect(onData).toHaveBeenNthCalledWith(1, { text: 'Hello ' });
    expect(onData).toHaveBeenNthCalledWith(2, { text: 'world' });
    expect(onProgress).toHaveBeenCalledWith({ phase: 'search', step: 1 });
    expect(onDone).toHaveBeenCalledWith({
      usage: { prompt_tokens: 3, output_tokens: 2, total_tokens: 5 },
      persistence: { ok: true },
    });
    expect(onError).not.toHaveBeenCalled();
  });

  it('dispatches a terminal error frame to onError (Requirement 2.6)', async () => {
    const frames = [
      'event: data\ndata: {"text":"partial"}\n\n',
      'event: error\ndata: {"action":"playground_generate","reason":"gateway exploded"}\n\n',
    ];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okSSEResponse(frames)));

    const onData = vi.fn();
    const onError = vi.fn();
    await fetchSSEStream('http://backend/generate', {}, { onData, onError });

    expect(onData).toHaveBeenCalledWith({ text: 'partial' });
    expect(onError).toHaveBeenCalledWith({ action: 'playground_generate', reason: 'gateway exploded' });
  });

  it('reports a backend non-2xx as an onError network failure', async () => {
    const badResponse = {
      ok: false,
      status: 502,
      body: null,
      text: async () => 'bad gateway',
    } as unknown as Response;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(badResponse));

    const onError = vi.fn();
    await fetchSSEStream('http://backend/generate', {}, { onError });

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].action).toBe('network_request');
    expect(onError.mock.calls[0][0].reason).toContain('502');
  });

  it('never constructs an EventSource', async () => {
    const frames = ['event: done\ndata: {}\n\n'];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okSSEResponse(frames)));
    const EventSourceSpy = vi.fn();
    vi.stubGlobal('EventSource', EventSourceSpy);

    await fetchSSEStream('http://backend/generate', {}, { onDone: vi.fn() });

    expect(EventSourceSpy).not.toHaveBeenCalled();
  });

  describe('60s AbortController timeout (Requirement 2.8)', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it('triggers an onError connection failure when the request hangs past 60s', async () => {
      // fetch never resolves: the only way out is the 60s AbortController timeout.
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

      const onError = vi.fn();
      const promise = fetchSSEStream('http://backend/slow', {}, { onError });

      // Advance just past the 60s threshold.
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
      await promise;

      expect(onError).toHaveBeenCalledTimes(1);
      expect(onError.mock.calls[0][0].action).toBe('connection_timeout');
      expect(onError.mock.calls[0][0].reason).toContain('60 seconds');
    });
  });
});
