/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { Search as SearchIcon, Globe, Info } from 'lucide-react';
import {
  Card,
  Button,
  Input,
  StreamingMarkdown,
  ErrorBanner,
  CitationList,
  PersistenceIndicator,
} from './SharedComponents';
import { fetchSSEStream, SERVICE_URLS, PROJECT_ENV_VARS } from '../lib/api';
import { HistoryRecord, SSEDataEvent, SSEDoneEvent, SSEErrorEvent } from '../types';

interface Citation {
  url: string;
  title: string;
}

interface WebAgentScreenProps {
  onAddHistory: (record: HistoryRecord) => void;
}

export const WebAgentScreen: React.FC<WebAgentScreenProps> = ({ onAddHistory }) => {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamedAnswer, setStreamedAnswer] = useState('');
  const [citations, setCitations] = useState<Citation[]>([]);
  const [persistenceOk, setPersistenceOk] = useState<boolean | null>(null);
  const [persistenceId, setPersistenceId] = useState<string>('');

  // States
  const [validationError, setValidationError] = useState('');
  const [searchError, setSearchError] = useState<SSEErrorEvent | null>(null);
  const [zeroOutcome, setZeroOutcome] = useState(false);

  const handleAsk = async () => {
    if (loading || isStreaming) return;

    const trimmed = question.trim();
    if (!trimmed) {
      setValidationError('Web query question cannot be blank.');
      return;
    }
    if (trimmed.length > 2000) {
      setValidationError(`Query exceeds 2000 max limit (${trimmed.length} characters).`);
      return;
    }

    setValidationError('');
    setStreamedAnswer('');
    setCitations([]);
    setSearchError(null);
    setZeroOutcome(false);
    setPersistenceOk(null);

    const baseUrl = SERVICE_URLS['web-agent'];
    if (!baseUrl) {
      setSearchError({
        action: 'web_agent_ask',
        reason: `Ask the Web backend is not configured. Set ${PROJECT_ENV_VARS['web-agent']} to its base URL.`,
      });
      return;
    }

    setLoading(true);

    let completeText = '';
    let finalMeta: SSEDoneEvent | null = null;
    let sError: SSEErrorEvent | null = null;
    let doneCitations: Citation[] = [];
    let zero = false;

    setIsStreaming(true);
    await fetchSSEStream(
      `${baseUrl}/ask`,
      { question: trimmed },
      {
        onData: (eventData: SSEDataEvent) => {
          setLoading(false);
          completeText += eventData.text;
          setStreamedAnswer(completeText);
        },
        onDone: (done: SSEDoneEvent) => {
          finalMeta = done;
          if (done.citations) {
            doneCitations = done.citations;
            setCitations(done.citations);
          }
          if ((!done.citations || done.citations.length === 0) && !completeText) {
            zero = true;
            setZeroOutcome(true);
          }
          if (done.persistence) {
            setPersistenceOk(done.persistence.ok);
            setPersistenceId(done.persistence.operation_id || '');
          }
        },
        onError: (err: SSEErrorEvent) => {
          sError = err;
          setSearchError(err);
        },
      },
    );

    setIsStreaming(false);
    setLoading(false);

    if (completeText || doneCitations.length > 0 || sError || zero) {
      const histRecord: HistoryRecord = {
        id: `web_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        projectId: 'web-agent',
        created_at: new Date().toISOString(),
        label: trimmed,
        inputs: { question: trimmed },
        outputs: {
          text: completeText || undefined,
          metadata: finalMeta || undefined,
          error: sError || undefined,
        },
      };
      onAddHistory(histRecord);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAsk();
    }
  };

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6 select-text">

      {/* Intro section */}
      <div className="flex flex-col gap-1.5 select-none text-center max-w-xl mx-auto mb-2">
        <div className="mx-auto p-2 border border-border-dim bg-surface rounded-md text-primary-main w-fit mb-2">
          <Globe className="w-5 h-5" />
        </div>
        <h2 className="text-xl font-bold font-sans tracking-tight text-white">Ask the Web</h2>
        <p className="text-xs text-text-muted">Retrieve direct contextual answers grounded in web citations.</p>
      </div>

      {/* Query Search Form bar */}
      <Card>
        <div className="flex flex-col sm:flex-row gap-3 items-stretch relative">
          <div className="flex-1 min-w-0">
            <Input
              id="web-question-search-bar"
              placeholder="What are the latest microservice orchestrators in 2026?..."
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading || isStreaming}
              error={validationError}
              mono
              className="w-full h-11 pl-10 pr-4"
            />
            <div className="absolute left-6 top-3 text-text-faint select-none">
              <SearchIcon className="w-4 h-4" />
            </div>
          </div>

          <Button
            variant="primary"
            onClick={handleAsk}
            disabled={loading || isStreaming || !question.trim()}
            isLoading={loading || isStreaming}
            className="h-11 px-6 font-semibold select-none text-xs"
          >
            <span>Retrieve Web Solution</span>
          </Button>
        </div>
      </Card>

      {/* Output Console area with multi-states */}
      {(loading || isStreaming || streamedAnswer || zeroOutcome || searchError || persistenceOk !== null) && (
        <Card title="Query Search Outcome">
          <div className="flex flex-col gap-5 min-h-[160px] select-text">

            {/* Initial Loader buffering */}
            {loading && !streamedAnswer && (
              <div
                role="status"
                aria-label="Loading"
                className="flex items-center gap-3 font-mono text-xs text-text-muted py-4 animate-pulse select-none"
              >
                <span className="w-2.5 h-2.5 bg-primary-main rounded-full animate-ping shrink-0" />
                <span>Interrogating web sources and assembling retrieval context...</span>
              </div>
            )}

            {/* In-case of stream Error */}
            {searchError && (
              <div className="my-1 shrink-0">
                <ErrorBanner action={searchError.action} reason={searchError.reason} onRetry={handleAsk} />
              </div>
            )}

            {/* Zero Results Outcomes (Requirement 6.5) */}
            {zeroOutcome && !searchError && (
              <div className="flex flex-col items-center justify-center p-8 text-center select-none bg-surface-2 bg-opacity-35 rounded border border-dashed border-border-dim my-2">
                <Info className="w-8 h-8 text-text-faint mb-2" />
                <span className="text-xs font-semibold text-text-muted">No relevant web sources found</span>
                <span className="text-[11px] text-text-faint mt-1 max-w-sm">The search returned zero matching results. Try expanding your query.</span>
              </div>
            )}

            {/* Stream display */}
            {streamedAnswer && !zeroOutcome && (
              <div className="flex-1 whitespace-pre-wrap leading-relaxed max-h-[500px] overflow-y-auto bg-surface-2 bg-opacity-20 border border-border-dim/50 rounded-lg p-5">
                <StreamingMarkdown content={streamedAnswer} isStreaming={isStreaming} />
              </div>
            )}

            {/* Footer markers: citations & persistence warn */}
            {(citations.length > 0 || (persistenceOk !== null && !persistenceOk)) && (
              <div className="flex flex-col gap-4 border-t border-border-dim pt-4 shrink-0 mt-2 select-none">
                {citations.length > 0 && <CitationList citations={citations} />}

                {persistenceOk !== null && !persistenceOk && (
                  <div className="self-start">
                    <PersistenceIndicator ok={persistenceOk} operationId={persistenceId} />
                  </div>
                )}
              </div>
            )}

          </div>
        </Card>
      )}

    </div>
  );
};
