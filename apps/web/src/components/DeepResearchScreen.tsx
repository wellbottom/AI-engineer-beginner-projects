/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { Search, ChevronDown, ChevronUp, BookOpen, FileText } from 'lucide-react';
import {
  Card,
  Button,
  Textarea,
  ErrorBanner,
  ProgressStep,
  ProgressStepper,
  CitationList,
  PersistenceIndicator,
} from './SharedComponents';
import { fetchSSEStream, SERVICE_URLS, PROJECT_ENV_VARS } from '../lib/api';
import { HistoryRecord, SSEDataEvent, SSEProgressEvent, SSEDoneEvent, SSEErrorEvent } from '../types';

interface DeepResearchScreenProps {
  onAddHistory: (record: HistoryRecord) => void;
}

const INITIAL_STEPS: ProgressStep[] = [
  { label: 'decomposition', status: 'pending', detail: 'Break the topic into sub-questions' },
  { label: 'search', status: 'pending', detail: 'Query web sources per sub-question' },
  { label: 'embedding', status: 'pending', detail: 'Store retrieved content in the vector store' },
  { label: 'synthesis', status: 'pending', detail: 'Compile the final cited report' },
];

export const DeepResearchScreen: React.FC<DeepResearchScreenProps> = ({ onAddHistory }) => {
  const [topic, setTopic] = useState('');

  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);

  const [steps, setSteps] = useState<ProgressStep[]>(INITIAL_STEPS);

  const [report, setReport] = useState<SSEDoneEvent['report'] | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<number, boolean>>({});
  const [persistenceMeta, setPersistenceMeta] = useState<{ ok: boolean; operation_id?: string } | null>(null);

  const [validationError, setValidationError] = useState('');
  const [researchError, setResearchError] = useState<SSEErrorEvent | null>(null);

  const toggleSection = (idx: number) => {
    setCollapsedSections((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const handleResearch = async () => {
    if (loading || isStreaming) return;

    const trimmed = topic.trim();
    if (!trimmed) {
      setValidationError('Topic description is required.');
      return;
    }

    setValidationError('');
    setReport(null);
    setResearchError(null);
    setPersistenceMeta(null);
    setCollapsedSections({});

    const baseUrl = SERVICE_URLS['deep-research'];
    if (!baseUrl) {
      setResearchError({
        action: 'deep_research',
        reason: `Deep Research backend is not configured. Set ${PROJECT_ENV_VARS['deep-research']} to its base URL.`,
      });
      return;
    }

    setLoading(true);
    setIsStreaming(true);
    setSteps([
      { label: 'decomposition', status: 'active', detail: 'Breaking the topic into sub-questions...' },
      { label: 'search', status: 'pending', detail: 'Awaiting sub-question decomposition' },
      { label: 'embedding', status: 'pending', detail: 'Awaiting retrieved content' },
      { label: 'synthesis', status: 'pending', detail: 'Awaiting vector-store indexing' },
    ]);

    let completedText = '';
    let finalMeta: SSEDoneEvent | null = null;
    let sError: SSEErrorEvent | null = null;
    let finalReport: SSEDoneEvent['report'] | null = null;

    await fetchSSEStream(
      `${baseUrl}/research`,
      { topic: trimmed },
      {
        onData: (eventData: SSEDataEvent) => {
          setLoading(false);
          completedText += eventData.text;
        },
        onProgress: (progress: SSEProgressEvent) => {
          setLoading(false);
          const phase = progress.phase.toLowerCase();
          const stepNum = progress.step;
          const desc = progress.detail || '';

          setSteps((prev) => {
            const clone = [...prev];
            const phaseIndices: Record<string, number> = {
              decomposition: 0,
              search: 1,
              embedding: 2,
              synthesis: 3,
            };
            const activeIdx = phaseIndices[phase];
            if (activeIdx !== undefined) {
              for (let i = 0; i < clone.length; i++) {
                if (i < activeIdx) clone[i] = { ...clone[i], status: 'done' };
                else if (i === activeIdx) clone[i] = { ...clone[i], status: 'active', detail: desc, elapsedMs: stepNum * 1000 };
                else clone[i] = { ...clone[i], status: 'pending' };
              }
            }
            return clone;
          });
        },
        onDone: (done: SSEDoneEvent) => {
          setLoading(false);
          setSteps((prev) => prev.map((s) => ({ ...s, status: 'done' })));
          if (done.report) {
            finalReport = done.report;
            setReport(done.report);
          }
          finalMeta = done;
          if (done.persistence) setPersistenceMeta(done.persistence);
        },
        onError: (err: SSEErrorEvent) => {
          sError = err;
          setResearchError(err);
          setSteps((prev) => prev.map((s) => (s.status === 'active' ? { ...s, status: 'failed', detail: err.reason } : s)));
        },
      },
    );

    setIsStreaming(false);
    setLoading(false);

    if (finalReport || completedText || sError) {
      const histRecord: HistoryRecord = {
        id: `deep_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        projectId: 'deep-research',
        created_at: new Date().toISOString(),
        label: trimmed,
        inputs: { topic: trimmed },
        outputs: {
          text: completedText || undefined,
          metadata: finalMeta || undefined,
          error: sError || undefined,
        },
      };
      onAddHistory(histRecord);
    }
  };

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6 select-text">

      {/* Intro section heading */}
      <div className="flex flex-col gap-1.5 select-none text-center max-w-xl mx-auto mb-2">
        <div className="mx-auto p-2 border border-border-dim bg-surface rounded-md text-primary-main w-fit mb-2">
          <BookOpen className="w-5 h-5" />
        </div>
        <h2 className="text-xl font-bold font-sans tracking-tight text-white">Deep Research Portal</h2>
        <p className="text-xs text-text-muted">Generate thorough cited reports via multi-phase web search and vector indexing.</p>
      </div>

      {/* Input panel block */}
      <Card title="Start Research Synthesis">
        <div className="flex flex-col gap-4">
          <Textarea
            id="research-topic-input-text"
            label="Target Topic or Industry Description"
            placeholder="Describe your target analysis context in detail..."
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            disabled={loading || isStreaming}
            error={validationError}
            maxLength={1000}
            mono
            className="min-h-[82px]"
          />

          <Button
            variant="primary"
            onClick={handleResearch}
            disabled={loading || isStreaming || !topic.trim()}
            isLoading={loading || isStreaming}
            className="w-full gap-2 text-xs font-semibold py-5 select-none"
          >
            <Search className="w-3.5 h-3.5 shrink-0" />
            <span>Generate Synthesis Report</span>
          </Button>
        </div>
      </Card>

      {/* Progressive Multi-Tier Stepper panel (Requirement 7.6) */}
      {(loading || isStreaming) && (
        <Card title="Orchestrator Execution Timeline">
          <div className="flex flex-col gap-4 py-2">
            <ProgressStepper steps={steps} />

            {loading && (
              <div
                role="status"
                aria-label="Loading"
                className="flex items-center gap-2.5 font-mono text-[11px] text-text-muted animate-pulse mt-2 pl-1 select-none"
              >
                <span className="w-2 h-2 bg-primary-main rounded-full animate-ping" />
                <span>Interrogating sources...</span>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Display errors if compile failed */}
      {researchError && (
        <div className="my-1 shrink-0 select-none">
          <ErrorBanner action={researchError.action} reason={researchError.reason} />
        </div>
      )}

      {/* Synthesis report display card */}
      {report && (
        <Card title="Assembled Research Outcomes">
          <div className="flex flex-col gap-6 select-text pt-2.5">

            <div className="flex flex-col gap-1 pr-4">
              <h1 className="text-2xl font-bold font-sans text-white tracking-tight">
                {report.title || 'Overview Synthesis'}
              </h1>
              {report.introduction && (
                <p className="text-sm font-sans text-text-muted leading-relaxed mt-2 select-text whitespace-pre-wrap">
                  {report.introduction}
                </p>
              )}
            </div>

            <div className="h-px bg-border-dim my-1 select-none" />

            <div className="space-y-4">
              {report.sections?.map((sect, sIdx: number) => {
                const isCollapsed = !!collapsedSections[sIdx];
                return (
                  <div key={sIdx} className="border border-border-dim bg-surface-2 bg-opacity-40 rounded-lg overflow-hidden transition-all">
                    <div
                      onClick={() => toggleSection(sIdx)}
                      className="flex items-center justify-between px-5 py-4 cursor-pointer hover:bg-surface-3 transition-colors select-none"
                    >
                      <div className="flex items-start gap-3.5 pr-4">
                        <span className="font-mono text-xs font-bold bg-surface border border-border-dim text-primary-main px-2 py-0.5 rounded shrink-0">
                          Q{sIdx + 1}
                        </span>
                        <h3 className="text-sm font-bold text-white font-sans text-left">{sect.sub_question}</h3>
                      </div>
                      <div className="text-text-faint shrink-0">
                        {isCollapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
                      </div>
                    </div>

                    {!isCollapsed && (
                      <div className="px-5 pb-5 pt-1.5 border-t border-border-dim/50 whitespace-pre-wrap select-text leading-relaxed text-sm text-text-muted font-sans font-normal border-opacity-75">
                        <p className="mb-4 text-text-main font-sans leading-relaxed">{sect.body}</p>
                        {sect.citations && sect.citations.length > 0 && (
                          <div className="mt-4 pt-4 border-t border-border-dim/50">
                            <CitationList citations={sect.citations} />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {report.conclusion && (
              <div className="mt-2 bg-primary-main/5 border border-primary-main/15 p-5 rounded-lg border-opacity-70 text-sm select-text">
                <h4 className="font-semibold text-white mb-2 flex items-center gap-1.5 font-sans select-none">
                  <FileText className="w-4 h-4 text-primary-main" />
                  <span>Final Synthesis conclusion</span>
                </h4>
                <p className="text-text-muted leading-relaxed font-sans">{report.conclusion}</p>
              </div>
            )}

            {persistenceMeta && !persistenceMeta.ok && (
              <div className="self-start pt-2 select-none border-t border-border-dim/75 w-full">
                <PersistenceIndicator ok={persistenceMeta.ok} operationId={persistenceMeta.operation_id} />
              </div>
            )}

          </div>
        </Card>
      )}

    </div>
  );
};
