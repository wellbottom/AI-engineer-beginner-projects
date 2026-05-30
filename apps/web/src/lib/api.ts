/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */
/// <reference types="vite/client" />

import {
  SSEDataEvent,
  SSEProgressEvent,
  SSEDoneEvent,
  SSEErrorEvent,
  HistoryRecord,
  ProjectId,
} from '../types';

// ============================================================================
// BACKEND BASE-URL CONFIG (Requirement 2.9)
// ============================================================================
//
// Each backend base URL is read from the SPA's own build-time environment via
// `import.meta.env`, using VITE_-prefixed variables. Vite only exposes variables
// matching its configured `envPrefix` (default "VITE_") on `import.meta.env`
// (see vite.config.ts), so these MUST use the VITE_ prefix — the previously
// generated NEXT_PUBLIC_* names would silently resolve to empty strings.
//
// `getServiceUrl(name)` reads exactly `VITE_<name>`. A non-VITE_-prefixed name
// therefore resolves to empty (the envPrefix guard), since this function only
// ever looks up the VITE_-prefixed key.

export function getServiceUrl(name: string): string {
  // Read import.meta.env directly (the literal access Vite/Vitest recognize).
  const metaEnv = import.meta.env as unknown as Record<string, unknown>;
  const value = metaEnv[`VITE_${name}`];
  return typeof value === 'string' ? value.trim() : '';
}

// SERVICE_URLS is keyed by the canonical ProjectId so `SERVICE_URLS[projectId]`
// resolves directly everywhere (screens and history views alike).
export const SERVICE_URLS: Record<ProjectId, string> = {
  playground: getServiceUrl('PLAYGROUND_URL'),
  support: getServiceUrl('SUPPORT_URL'),
  'web-agent': getServiceUrl('WEBAGENT_URL'),
  'deep-research': getServiceUrl('DEEPRESEARCH_URL'),
  image: getServiceUrl('IMAGE_URL'),
  capstone: getServiceUrl('CAPSTONE_URL'),
};

// The VITE_* variable name backing each project (used for clear config errors).
export const PROJECT_ENV_VARS: Record<ProjectId, string> = {
  playground: 'VITE_PLAYGROUND_URL',
  support: 'VITE_SUPPORT_URL',
  'web-agent': 'VITE_WEBAGENT_URL',
  'deep-research': 'VITE_DEEPRESEARCH_URL',
  image: 'VITE_IMAGE_URL',
  capstone: 'VITE_CAPSTONE_URL',
};

// Human-readable mini-project names for error messages (Requirement 13.6).
export const PROJECT_NAMES: Record<ProjectId, string> = {
  playground: 'LLM Playground',
  support: 'Support Chatbot',
  'web-agent': 'Ask the Web',
  'deep-research': 'Deep Research',
  image: 'Image Service',
  capstone: 'Capstone Agent',
};

/** Overall request timeout the frontend enforces (Requirements 2.8, 13.6). */
export const REQUEST_TIMEOUT_MS = 60_000;

// ============================================================================
// SSE FRAME PARSER (pure, testable — Requirement 2.5)
// ============================================================================

export interface ParsedSSEFrame {
  /** The `event:` type (empty string when no event line was present). */
  event: string;
  /** The concatenated `data:` payload (multiple data lines joined by "\n"). */
  data: string;
}

/**
 * Parse as many complete SSE frames as are available in `buffer`, returning the
 * parsed frames plus any trailing partial frame still to be completed by a later
 * chunk. Frames are separated by a blank line (`\n\n` or `\r\n\r\n`); within a
 * frame, `event:` and `data:` lines are extracted (multiple `data:` lines are
 * concatenated with "\n" per the SSE spec). A partial final frame (no trailing
 * blank line yet) is returned in `rest` so it can be buffered across chunks.
 */
export function parseSSEChunk(buffer: string): { frames: ParsedSSEFrame[]; rest: string } {
  // Normalize CRLF to LF so framing logic only deals with "\n".
  const normalized = buffer.replace(/\r\n/g, '\n');
  const segments = normalized.split('\n\n');
  // The last segment is an incomplete frame unless `buffer` ended with a blank
  // line (in which case the last segment is an empty string).
  const rest = segments.pop() ?? '';

  const frames: ParsedSSEFrame[] = [];
  for (const segment of segments) {
    const frame = parseSingleFrame(segment);
    if (frame) frames.push(frame);
  }
  return { frames, rest };
}

function parseSingleFrame(segment: string): ParsedSSEFrame | null {
  let event = '';
  const dataLines: string[] = [];
  let sawField = false;

  for (const rawLine of segment.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (line.trim() === '') continue;
    const colonIdx = line.indexOf(':');
    if (colonIdx === -1) continue;
    const field = line.slice(0, colonIdx).trim();
    // Per SSE spec a single leading space after the colon is stripped.
    let value = line.slice(colonIdx + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    if (field === 'event') {
      event = value.trim();
      sawField = true;
    } else if (field === 'data') {
      dataLines.push(value);
      sawField = true;
    }
  }

  if (!sawField) return null;
  return { event, data: dataLines.join('\n') };
}

// ============================================================================
// SSE CLIENT (POST + ReadableStream via fetch — NOT EventSource)
// ============================================================================
//
// EventSource is GET-only and cannot send a JSON request body, so this client
// is built on `fetch` + `response.body.getReader()`. It buffers the byte stream,
// splits frames with `parseSSEChunk`, JSON-parses each `data:` payload, and
// dispatches to the right handler. It enforces an overall 60s timeout via an
// AbortController and surfaces connection failures / timeouts through `onError`
// (Requirements 2.5, 2.6, 2.8).

interface StreamHandlers {
  onData?: (data: SSEDataEvent) => void;
  onProgress?: (progress: SSEProgressEvent) => void;
  onDone?: (done: SSEDoneEvent) => void;
  onError?: (error: SSEErrorEvent) => void;
}

export async function fetchSSEStream(
  url: string,
  bodyObj: unknown,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const controller = new AbortController();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', () => controller.abort());
  }

  let timedOut = false;
  // Overall 60s timeout covering the whole stream, not just the initial
  // connection (Requirement 2.8).
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
    handlers.onError?.({
      action: 'connection_timeout',
      reason: 'Request did not respond within 60 seconds.',
    });
  }, REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(bodyObj),
      signal: controller.signal,
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      throw new Error(
        `Server returned status ${response.status}${errText ? `: ${errText}` : ''}`,
      );
    }
    if (!response.body) {
      throw new Error('Response body is empty or not readable.');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const { frames, rest } = parseSSEChunk(buffer);
      buffer = rest;
      for (const frame of frames) {
        dispatchFrame(frame, handlers);
      }
    }

    // Flush any trailing complete frame left in the buffer.
    const tail = buffer + decoder.decode();
    if (tail.trim()) {
      const { frames } = parseSSEChunk(tail + '\n\n');
      for (const frame of frames) dispatchFrame(frame, handlers);
    }
  } catch (error) {
    const err = error as Error;
    if (err.name === 'AbortError') {
      // A timeout already reported via onError; an external abort is silent.
      return;
    }
    handlers.onError?.({
      action: 'network_request',
      reason: err.message || 'The streaming request failed.',
    });
  } finally {
    if (!timedOut) clearTimeout(timeoutId);
  }
}

function dispatchFrame(frame: ParsedSSEFrame, handlers: StreamHandlers): void {
  if (!frame.data) return;
  let payload: unknown;
  try {
    payload = JSON.parse(frame.data);
  } catch {
    // Ignore non-JSON keep-alive/comment frames.
    return;
  }

  switch (frame.event) {
    case 'data':
      handlers.onData?.(payload as SSEDataEvent);
      break;
    case 'progress':
      handlers.onProgress?.(payload as SSEProgressEvent);
      break;
    case 'done':
      handlers.onDone?.(payload as SSEDoneEvent);
      break;
    case 'error':
      handlers.onError?.(payload as SSEErrorEvent);
      break;
    default:
      // Unlabeled frame: treat as a content chunk only if it looks like one.
      if ((payload as SSEDataEvent)?.text !== undefined) {
        handlers.onData?.(payload as SSEDataEvent);
      }
      break;
  }
}

// ============================================================================
// CONFIG WARNINGS
// ============================================================================

/**
 * Returns a human-readable advisory listing any backend whose VITE_* base URL is
 * not configured, or null when all six are set. Surfaced on the dashboard so an
 * unconfigured backend is obvious (a missing URL produces a clear error on use,
 * never a fabricated response).
 */
export function getEnvWarningMsg(): string | null {
  const missing = (Object.keys(SERVICE_URLS) as ProjectId[])
    .filter((id) => !SERVICE_URLS[id])
    .map((id) => PROJECT_ENV_VARS[id]);

  if (missing.length > 0) {
    return `The following backend base URLs are not configured: ${missing.join(
      ', ',
    )}. Requests to those projects will report a configuration error until the VITE_* variables are set.`;
  }
  return null;
}

class BackendNotConfiguredError extends Error {
  constructor(projectId: ProjectId) {
    super(
      `${PROJECT_NAMES[projectId]} backend is not configured. Set ${PROJECT_ENV_VARS[projectId]} to its base URL.`,
    );
    this.name = 'BackendNotConfiguredError';
  }
}

function requireBaseUrl(projectId: ProjectId): string {
  const baseUrl = SERVICE_URLS[projectId];
  if (!baseUrl) throw new BackendNotConfiguredError(projectId);
  return baseUrl;
}

// ============================================================================
// HISTORY (real backend — Requirements 13.1, 13.3, 13.6). No local fallback.
// ============================================================================

async function fetchJsonWithTimeout(url: string): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Fetch a mini-project's persisted history list from its real backend
 * (`GET /history`). On failure or a 60s timeout this REJECTS with an error that
 * identifies the failed history retrieval and the affected project
 * (Requirement 13.6) — there is no silent local fallback.
 */
export async function getRemoteHistory(projectId: ProjectId): Promise<HistoryRecord[]> {
  const baseUrl = requireBaseUrl(projectId);
  let res: Response;
  try {
    res = await fetchJsonWithTimeout(`${baseUrl}/history`);
  } catch (err) {
    const e = err as Error;
    const detail = e.name === 'AbortError' ? 'timed out after 60 seconds' : e.message;
    throw new Error(
      `History retrieval failed for ${PROJECT_NAMES[projectId]}: ${detail}.`,
    );
  }
  if (!res.ok) {
    throw new Error(
      `History retrieval failed for ${PROJECT_NAMES[projectId]} (status ${res.status}).`,
    );
  }
  return (await res.json()) as HistoryRecord[];
}

/**
 * Fetch the full details of a single persisted record (`GET /history/{id}`).
 * Same failure/timeout semantics as getRemoteHistory (Requirement 13.6).
 */
export async function getRemoteHistoryDetail(
  projectId: ProjectId,
  id: string,
): Promise<HistoryRecord> {
  const baseUrl = requireBaseUrl(projectId);
  let res: Response;
  try {
    res = await fetchJsonWithTimeout(`${baseUrl}/history/${id}`);
  } catch (err) {
    const e = err as Error;
    const detail = e.name === 'AbortError' ? 'timed out after 60 seconds' : e.message;
    throw new Error(
      `History retrieval failed for ${PROJECT_NAMES[projectId]}: ${detail}.`,
    );
  }
  if (!res.ok) {
    if (res.status === 404) {
      throw new Error(
        `History record ${id} was not found for ${PROJECT_NAMES[projectId]}.`,
      );
    }
    throw new Error(
      `History retrieval failed for ${PROJECT_NAMES[projectId]} (status ${res.status}).`,
    );
  }
  return (await res.json()) as HistoryRecord;
}

// ============================================================================
// IMAGE ENDPOINTS (Image_Service)
// ============================================================================

export interface GenerateImageResult {
  mime_type: string;
  data_base64: string;
  persistence?: { ok: boolean; operation_id?: string };
}

export async function generateImage(
  prompt: string,
  model?: string,
): Promise<GenerateImageResult> {
  const baseUrl = requireBaseUrl('image');
  const res = await fetch(`${baseUrl}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, model }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Image generation failed${text ? `: ${text}` : ` (status ${res.status})`}.`);
  }
  return (await res.json()) as GenerateImageResult;
}

/** Lists the image-generation model identifiers offered by the backend. */
export async function getImageModels(): Promise<string[]> {
  const baseUrl = SERVICE_URLS.image;
  if (!baseUrl) return [];
  const res = await fetch(`${baseUrl}/models`, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) throw new Error(`Failed to load image models (status ${res.status}).`);
  return (await res.json()) as string[];
}

// ============================================================================
// CAPSTONE DOCUMENT INGESTION
// ============================================================================

export async function uploadCapstoneDocuments(
  files: File[],
): Promise<Array<{ filename: string; size?: number }>> {
  const baseUrl = requireBaseUrl('capstone');
  const formData = new FormData();
  files.forEach((f) => formData.append('documents', f));

  const res = await fetch(`${baseUrl}/documents`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Document ingestion failed${text ? `: ${text}` : ` (status ${res.status})`}.`);
  }
  return (await res.json()) as Array<{ filename: string; size?: number }>;
}

// ============================================================================
// SUPPORT CHATBOT SESSIONS
// ============================================================================

export async function createChatSession(): Promise<{ session_id: string }> {
  const baseUrl = requireBaseUrl('support');
  const res = await fetch(`${baseUrl}/session`, { method: 'POST' });
  if (!res.ok) throw new Error(`Could not establish a chatbot session (status ${res.status}).`);
  return (await res.json()) as { session_id: string };
}

export async function deleteChatSession(id: string): Promise<void> {
  const baseUrl = SERVICE_URLS.support;
  if (!baseUrl) return;
  await fetch(`${baseUrl}/session/${id}`, { method: 'DELETE' }).catch(() => undefined);
}
