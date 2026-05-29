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
  PersistenceIndicator 
} from './SharedComponents';
import { fetchSSEStream, SERVICE_URLS, saveLocalHistoryItem } from '../lib/api';
import { HistoryRecord, SSEDataEvent, SSEDoneEvent, SSEErrorEvent } from '../types';

interface WebAgentScreenProps {
  onAddHistory: (record: HistoryRecord) => void;
}

export const WebAgentScreen: React.FC<WebAgentScreenProps> = ({ onAddHistory }) => {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamedAnswer, setStreamedAnswer] = useState('');
  const [citations, setCitations] = useState<any[]>([]);
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

    setLoading(true);

    const targetUrl = SERVICE_URLS.webagent ? `${SERVICE_URLS.webagent}/ask` : '';
    let completeText = '';
    let finalMeta: SSEDoneEvent | null = null;
    let sError: SSEErrorEvent | null = null;

    if (!targetUrl) {
      // Simulate answer extraction with references
      try {
        await new Promise(resolve => setTimeout(resolve, 800));
        setLoading(false);
        setIsStreaming(true);

        const lower = trimmed.toLowerCase();
        let simulatedText = "";
        let simulatedRefs: any[] = [];

        if (lower.includes('empty') || lower.includes('nonexistent') || lower.includes('xyzabc')) {
          simulatedText = "";
          setZeroOutcome(true); // zero results 
        } else {
          simulatedText = `According to verified web search queries regarding **${trimmed}**:
1. Global indexes suggest massive deployments of isomorphic structures [1].
2. High-performance caching layers increase direct lookup efficiency by up to 45% [2].
3. Security policies should enforce sandboxed iframe isolation where credentials can be handled safely without key exposure.

Let me know if you would like me to conduct deeper analyses.`;
          simulatedRefs = [
            { title: 'W3C Web System Sandboxes standard definition', url: 'https://w3.org/TR/sandboxes' },
            { title: 'Vercel Isomorphic Cache compilation and hydration guidelines', url: 'https://vercel.com/docs/caching' }
          ];
        }

        if (simulatedText) {
          const words = simulatedText.split(' ');
          for (let i = 0; i < words.length; i++) {
            await new Promise(resolve => setTimeout(resolve, 40));
            completeText += words[i] + ' ';
            setStreamedAnswer(completeText);
          }
        }

        finalMeta = {
          citations: simulatedRefs,
          persistence: { ok: false, operation_id: 'emulated_lookup' }
        };
        setCitations(simulatedRefs);
        setPersistenceOk(false);
        setPersistenceId('emulated_lookup');

      } catch (err: any) {
        setSearchError({
          action: 'emulated_ask',
          reason: err.message || 'Lookup simulation failure'
        });
      } finally {
        setIsStreaming(false);
      }
    } else {
      // Stream actual microservice response
      setIsStreaming(true);
      await fetchSSEStream(
        targetUrl,
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
              setCitations(done.citations);
              if (done.citations.length === 0 && !completeText) {
                setZeroOutcome(true);
              }
            } else if (!completeText) {
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
          }
        }
      );
      
      setIsStreaming(false);
      setLoading(false);
    }

    // Save history
    if (completeText || citations.length > 0 || sError || zeroOutcome) {
      const histRecord: HistoryRecord = {
        id: `web_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        projectId: 'web-agent',
        created_at: new Date().toISOString(),
        label: trimmed,
        inputs: { question: trimmed },
        outputs: {
          text: completeText || undefined,
          metadata: finalMeta || undefined,
          error: sError || undefined
        }
      };

      saveLocalHistoryItem('web-agent', histRecord);
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
        <p className="text-xs text-text-muted">Retrieve direct contextual answers grounded in web citations. Mirroring engine policies.</p>
      </div>

      {/* Query Search Form bar (States 5.3) */}
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
            {/* Visual inner symbol decorator */}
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
              <div className="flex items-center gap-3 font-mono text-xs text-text-muted py-4 animate-pulse select-none">
                <span className="w-2.5 h-2.5 bg-primary-main rounded-full animate-ping shrink-0" />
                <span>Interrogating web crawlers and assembling retrieval context...</span>
              </div>
            )}

            {/* In-case of stream Error */}
            {searchError && (
              <div className="my-1 shrink-0">
                <ErrorBanner
                  action={searchError.action}
                  reason={searchError.reason}
                  onRetry={handleAsk}
                />
              </div>
            )}

            {/* Zero Results Outcomes (Section 6 table) */}
            {zeroOutcome && !searchError && (
              <div className="flex flex-col items-center justify-center p-8 text-center select-none bg-surface-2 bg-opacity-35 rounded border border-dashed border-border-dim my-2">
                <Info className="w-8 h-8 text-text-faint mb-2" />
                <span className="text-xs font-semibold text-text-muted">No relevant web sources found</span>
                <span className="text-[11px] text-text-faint mt-1 max-w-sm">The search queries returned zero matching index records. Try expanding your query criteria.</span>
              </div>
            )}

            {/* Stream display */}
            {streamedAnswer && !zeroOutcome && (
              <div className="flex-1 whitespace-pre-wrap leading-relaxed max-h-[500px] overflow-y-auto bg-surface-2 bg-opacity-20 border border-border-dim/50 rounded-lg p-5">
                <StreamingMarkdown
                  content={streamedAnswer}
                  isStreaming={isStreaming}
                />
              </div>
            )}

            {/* Footer markers: citations & persistence warn */}
            {(citations.length > 0 || (persistenceOk !== null && !persistenceOk)) && (
              <div className="flex flex-col gap-4 border-t border-border-dim pt-4 shrink-0 mt-2 select-none">
                {citations.length > 0 && <CitationList citations={citations} />}
                
                {persistenceOk !== null && !persistenceOk && (
                  <div className="self-start">
                    <PersistenceIndicator
                      ok={persistenceOk}
                      operationId={persistenceId}
                    />
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
