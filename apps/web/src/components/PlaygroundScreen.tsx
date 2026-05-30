/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { Play } from 'lucide-react';
import {
  Card,
  Button,
  Textarea,
  Input,
  StreamingMarkdown,
  ErrorBanner,
  TokenUsage,
  PersistenceIndicator,
} from './SharedComponents';
import { fetchSSEStream, SERVICE_URLS, PROJECT_ENV_VARS } from '../lib/api';
import {
  HistoryRecord,
  SSEDataEvent,
  SSEDoneEvent,
  SSEErrorEvent,
} from '../types';

// The LLM default model identifier fixed by the design (Requirement 3.4 / 2.x).
const DEFAULT_MODEL = 'claude-opus-4.7';

interface PlaygroundScreenProps {
  onAddHistory: (record: HistoryRecord) => void;
}

export const PlaygroundScreen: React.FC<PlaygroundScreenProps> = ({ onAddHistory }) => {
  const [prompt, setPrompt] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [model, setModel] = useState(DEFAULT_MODEL);

  // Request & streaming states
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamedText, setStreamedText] = useState('');
  const [doneMetadata, setDoneMetadata] = useState<SSEDoneEvent | null>(null);

  // Errors state
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});
  const [streamError, setStreamError] = useState<SSEErrorEvent | null>(null);

  const validate = (): boolean => {
    const errors: Record<string, string> = {};

    if (!prompt.trim()) {
      errors.prompt = 'Source prompt is required.';
    } else if (prompt.length > 8000) {
      errors.prompt = `Prompt length exceeds 8000 characters limit (currently ${prompt.length}).`;
    }
    if (systemPrompt && systemPrompt.length > 4000) {
      errors.systemPrompt = `System prompt length exceeds 4000 characters limit (currently ${systemPrompt.length}).`;
    }
    if (temperature < 0.0 || temperature > 2.0) {
      errors.temperature = 'Temperature must be between 0.0 and 2.0.';
    }
    if (maxTokens < 1 || maxTokens > 4096) {
      errors.maxTokens = 'Max tokens must be between 1 and 4096.';
    }

    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleRun = async () => {
    if (loading || isStreaming) return;
    if (!validate()) return;

    setLoading(true);
    setStreamedText('');
    setDoneMetadata(null);
    setStreamError(null);

    const baseUrl = SERVICE_URLS.playground;
    if (!baseUrl) {
      // Missing backend URL -> clear configuration error, never a fake stream.
      setLoading(false);
      setStreamError({
        action: 'playground_generate',
        reason: `LLM Playground backend is not configured. Set ${PROJECT_ENV_VARS.playground} to its base URL.`,
      });
      return;
    }

    setIsStreaming(true);

    const body = {
      prompt,
      system_prompt: systemPrompt || undefined,
      temperature,
      max_tokens: maxTokens,
      model: model || undefined,
    };

    let completeText = '';
    let finalMeta: SSEDoneEvent | null = null;
    let sError: SSEErrorEvent | null = null;

    await fetchSSEStream(
      `${baseUrl}/generate`,
      body,
      {
        onData: (eventData: SSEDataEvent) => {
          setLoading(false);
          completeText += eventData.text;
          setStreamedText(completeText);
        },
        onDone: (doneEvent: SSEDoneEvent) => {
          finalMeta = doneEvent;
          setDoneMetadata(doneEvent);
        },
        onError: (errEvent: SSEErrorEvent) => {
          sError = errEvent;
          setStreamError(errEvent);
        },
      },
    );

    setIsStreaming(false);
    setLoading(false);

    // Surface the run in the in-app history list (backend persists the record).
    if (completeText || sError || finalMeta) {
      const histRecord: HistoryRecord = {
        id: `play_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        projectId: 'playground',
        created_at: new Date().toISOString(),
        label: prompt.length > 50 ? `${prompt.substring(0, 50)}...` : prompt,
        inputs: {
          prompt,
          system_prompt: systemPrompt || undefined,
          temperature,
          max_tokens: maxTokens,
          model,
        },
        outputs: {
          text: completeText || undefined,
          metadata: finalMeta || undefined,
          error: sError || undefined,
        },
      };
      onAddHistory(histRecord);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleRun();
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">

      {/* LEFT Parameters & Input Panel (5 columns) */}
      <div className="lg:col-span-5 flex flex-col gap-5">

        {/* Model parameters */}
        <Card title="Sandbox Parameters">
          <div className="flex flex-col gap-4">

            {/* Model Selector Name */}
            <Input
              id="model-selector-id"
              label="Model Architecture Override"
              placeholder={`e.g. ${DEFAULT_MODEL}`}
              value={model}
              onChange={(e) => setModel(e.target.value)}
              mono
            />

            {/* Temperature slide */}
            <div className="flex flex-col gap-1.5 select-none pt-1">
              <div className="flex justify-between items-center text-xs font-semibold">
                <label htmlFor="temp-slider-id" className="text-text-muted">Temperature</label>
                <span className="font-mono text-primary-main">{temperature.toFixed(2)}</span>
              </div>
              <input
                id="temp-slider-id"
                type="range"
                min="0.0"
                max="2.0"
                step="0.05"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="w-full h-1 bg-surface-3 rounded-lg appearance-none cursor-pointer accent-primary-main focus:outline-none"
              />
              <div className="flex justify-between text-[10px] text-text-faint font-mono">
                <span>0.0 (Deterministic)</span>
                <span>2.0 (Creative)</span>
              </div>
              {validationErrors.temperature && (
                <span className="text-xs text-danger-subtle font-medium mt-1">{validationErrors.temperature}</span>
              )}
            </div>

            {/* Max Token input step */}
            <div className="flex items-center gap-6 pt-1 select-none">
              <Input
                id="max-token-stepper-id"
                label="Maximum Token Length"
                type="number"
                min={1}
                max={4096}
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value) || 1)}
                error={validationErrors.maxTokens}
                mono
                className="w-full"
              />
            </div>

            {/* System directive */}
            <Textarea
              id="system-prompt-textarea-id"
              label="System Blueprint Persona Instruction"
              placeholder="Inject hidden constraints, output formats, or context directives..."
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              maxLength={4000}
              error={validationErrors.systemPrompt}
              mono
            />

          </div>
        </Card>

        {/* Core Prompt message Area */}
        <Card title="Source Prompt Canvas">
          <div className="flex flex-col gap-4">
            <Textarea
              id="main-prompt-textarea-id"
              placeholder="Structure your text prompt or raw code query here (Cmd + Enter compiles)..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              maxLength={8000}
              error={validationErrors.prompt}
              mono
            />

            <Button
              id="run-playground-btn"
              variant="primary"
              onClick={handleRun}
              isLoading={loading || isStreaming}
              className="w-full gap-2 text-xs font-semibold py-5"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Compile &amp; Run Gateway Stream</span>
            </Button>
          </div>
        </Card>

      </div>

      {/* RIGHT Streaming Output Panel (7 columns) */}
      <div className="lg:col-span-7 flex flex-col gap-5">
        <Card title="Raw Stream Console output">
          <div className="flex flex-col gap-5 min-h-[440px] select-text">

            {/* Stream output display screen states */}
            {!loading && !isStreaming && !streamedText && !streamError && (
              <div className="flex-1 flex flex-col items-center justify-center text-center py-24 select-none">
                <Play className="w-8 h-8 text-text-faint mb-2" />
                <span className="text-xs font-semibold text-text-muted">Console idle</span>
                <span className="text-[11px] text-text-faint mt-0.5">Parameters primed. Trigger execute above to stream results.</span>
              </div>
            )}

            {/* Loading Initial Response */}
            {loading && !streamedText && (
              <div
                role="status"
                aria-label="Loading"
                className="flex items-center gap-3 py-4 text-xs font-mono text-text-muted animate-pulse select-none"
              >
                <span className="w-2.5 h-2.5 bg-primary-main rounded-full animate-ping" />
                <span>Synchronizing endpoint and allocating execution resources...</span>
              </div>
            )}

            {/* Render Error if any */}
            {streamError && (
              <div className="my-1">
                <ErrorBanner
                  action={streamError.action}
                  reason={streamError.reason}
                  onRetry={handleRun}
                />
              </div>
            )}

            {/* Rendering content chunks stream */}
            {streamedText && (
              <div className="flex-1 pr-2 max-h-[600px] overflow-y-auto leading-relaxed border border-border-dim/50 rounded-lg p-5 bg-surface-2 bg-opacity-30">
                <StreamingMarkdown
                  content={streamedText}
                  isStreaming={isStreaming}
                />
              </div>
            )}

            {/* Usage metadata tokens metrics */}
            {doneMetadata && (
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-t border-border-dim pt-4 shrink-0 select-none">
                <TokenUsage
                  promptTokens={doneMetadata.usage?.prompt_tokens}
                  outputTokens={doneMetadata.usage?.output_tokens}
                  totalTokens={doneMetadata.usage?.total_tokens}
                />

                {doneMetadata.persistence && (
                  <PersistenceIndicator
                    ok={doneMetadata.persistence.ok}
                    operationId={doneMetadata.persistence.operation_id}
                  />
                )}
              </div>
            )}

          </div>
        </Card>
      </div>

    </div>
  );
};
