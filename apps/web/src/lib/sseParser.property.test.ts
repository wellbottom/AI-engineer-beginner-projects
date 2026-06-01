/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */
//
// Task 16.6 — frontend property test for the SSE frame parser helper.
//
// Feature: ai-engineer-practice-monorepo, Frontend SSE-parser property:
// for any sequence of well-formed SSE frames serialized as `event:`/`data:`
// lines terminated by a blank line, splitting the serialized byte stream into
// ARBITRARY chunks and feeding them through parseSSEChunk (buffering the
// returned `rest` across chunks) recovers exactly the original frames, in order,
// regardless of where the chunk boundaries fall (partial frames are buffered).
// Validates: Requirement 2.5

import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { parseSSEChunk, type ParsedSSEFrame } from './api';

// A single SSE data line value: no CR/LF (newlines would create new lines /
// frame boundaries) and no leading space (the parser strips exactly one leading
// space after the colon, which we account for by construction).
const dataValueArb = fc
  .string({ minLength: 0, maxLength: 40 })
  .map((s) => s.replace(/[\r\n]/g, ''))
  .map((s) => (s.startsWith(' ') ? s.slice(1) : s));

// A non-empty event token: no whitespace, colon, or newline.
const eventArb = fc
  .string({ minLength: 1, maxLength: 12 })
  .map((s) => s.replace(/[\s:]/g, ''))
  .filter((s) => s.length > 0);

const frameArb: fc.Arbitrary<ParsedSSEFrame> = fc.record({
  event: eventArb,
  data: dataValueArb,
});

function serialize(frame: ParsedSSEFrame): string {
  // One leading space after each colon (standard SSE; the parser strips it).
  return `event: ${frame.event}\ndata: ${frame.data}\n\n`;
}

// Split `text` into chunks per the given positive sizes; trailing remainder is a
// final chunk. An empty sizes array yields the whole string as one chunk.
function chunkBySizes(text: string, sizes: number[]): string[] {
  const chunks: string[] = [];
  let i = 0;
  for (const size of sizes) {
    if (i >= text.length) break;
    chunks.push(text.slice(i, i + size));
    i += size;
  }
  if (i < text.length) chunks.push(text.slice(i));
  return chunks;
}

// Drive parseSSEChunk exactly the way fetchSSEStream does: accumulate `rest`.
function feed(chunks: string[]): ParsedSSEFrame[] {
  let buffer = '';
  const collected: ParsedSSEFrame[] = [];
  for (const chunk of chunks) {
    buffer += chunk;
    const { frames, rest } = parseSSEChunk(buffer);
    collected.push(...frames);
    buffer = rest;
  }
  return collected;
}

describe('parseSSEChunk robustness (Requirement 2.5)', () => {
  it('recovers all frames regardless of chunk boundaries', () => {
    fc.assert(
      fc.property(
        fc.array(frameArb, { minLength: 0, maxLength: 8 }),
        fc.array(fc.integer({ min: 1, max: 7 }), { maxLength: 40 }),
        (frames, sizes) => {
          const full = frames.map(serialize).join('');
          const chunks = chunkBySizes(full, sizes);
          const parsed = feed(chunks);
          expect(parsed).toEqual(frames);
        },
      ),
      { numRuns: 300 },
    );
  });

  it('also recovers frames when CRLF line endings are used', () => {
    fc.assert(
      fc.property(fc.array(frameArb, { minLength: 1, maxLength: 6 }), (frames) => {
        const full = frames
          .map((f) => `event: ${f.event}\r\ndata: ${f.data}\r\n\r\n`)
          .join('');
        const parsed = feed([full]);
        expect(parsed).toEqual(frames);
      }),
      { numRuns: 200 },
    );
  });

  it('buffers a partial trailing frame until its blank line arrives', () => {
    const { frames, rest } = parseSSEChunk('event: data\ndata: {"text":"hi"}\n\nevent: do');
    expect(frames).toEqual([{ event: 'data', data: '{"text":"hi"}' }]);
    expect(rest).toBe('event: do');
  });
});
