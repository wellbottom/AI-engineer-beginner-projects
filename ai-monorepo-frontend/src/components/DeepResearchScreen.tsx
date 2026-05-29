/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { Search, ChevronDown, ChevronUp, BookOpen, AlertCircle, FileText } from 'lucide-react';
import { 
  Card, 
  Button, 
  Textarea, 
  StreamingMarkdown, 
  ErrorBanner, 
  ProgressStep, 
  ProgressStepper, 
  CitationList, 
  PersistenceIndicator 
} from './SharedComponents';
import { fetchSSEStream, SERVICE_URLS, saveLocalHistoryItem } from '../lib/api';
import { HistoryRecord, SSEDataEvent, SSEProgressEvent, SSEDoneEvent, SSEErrorEvent } from '../types';

interface DeepResearchScreenProps {
  onAddHistory: (record: HistoryRecord) => void;
}

export const DeepResearchScreen: React.FC<DeepResearchScreenProps> = ({ onAddHistory }) => {
  const [topic, setTopic] = useState('');
  
  // States of execution
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  
  // Progress stepper phases
  const [steps, setSteps] = useState<ProgressStep[]>([
    { label: 'topic decomposition', status: 'pending', detail: 'Analyze query target parameters' },
    { label: 'web search grounding', status: 'pending', detail: 'Index-crawl targeted search matrices' },
    { label: 'vector embedding indexing', status: 'pending', detail: 'Inject context into local similarity cache' },
    { label: 'report synthesis', status: 'pending', detail: 'Consolidate subsections in technical Markdown' }
  ]);
  
  // Final Synthesis report outputs
  const [report, setReport] = useState<any | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<number, boolean>>({});
  const [persistenceMeta, setPersistenceMeta] = useState<any>(null);

  // Errors management
  const [validationError, setValidationError] = useState('');
  const [researchError, setResearchError] = useState<SSEErrorEvent | null>(null);

  const toggleSection = (idx: number) => {
    setCollapsedSections(prev => ({
      ...prev,
      [idx]: !prev[idx]
    }));
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

    setLoading(true);
    setIsStreaming(true);

    // Initial reset of progress stepper: decomposition -> pending,,
    setSteps([
      { label: 'decomposition', status: 'active', detail: 'Breaking query into sub-questions...', elapsedMs: 500 },
      { label: 'search', status: 'pending', detail: 'Awaiting sub-question decomposition' },
      { label: 'embedding', status: 'pending', detail: 'Awaiting crawl datasets' },
      { label: 'synthesis', status: 'pending', detail: 'Awaiting index compilation' }
    ]);

    const targetUrl = SERVICE_URLS.deepresearch ? `${SERVICE_URLS.deepresearch}/research` : '';
    let completedText = '';
    let finalMeta: SSEDoneEvent | null = null;
    let sError: SSEErrorEvent | null = null;

    if (!targetUrl) {
      // Stream simulation with progressive phase updates
      try {
        const delays = [1500, 2000, 2000, 1500];
        
        // 1. decomposition
        await new Promise(resolve => setTimeout(resolve, delays[0]));
        setLoading(false);
        setSteps(prev => [
          { ...prev[0], status: 'done', detail: 'Topic broken into 3 strategic sub-questions.', elapsedMs: 1500 },
          { ...prev[1], status: 'active', detail: 'Searching databases for query components...', elapsedMs: 3500 },
          prev[2],
          prev[3]
        ]);

        // 2. search
        await new Promise(resolve => setTimeout(resolve, delays[1]));
        setSteps(prev => [
          prev[0],
          { ...prev[1], status: 'done', detail: 'Fetched 14 matched index rows from Google Search.', elapsedMs: 3500 },
          { ...prev[2], status: 'active', detail: 'Hydrating vector nodes and scaling similarities...', elapsedMs: 5500 },
          prev[3]
        ]);

        // 3. embedding
        await new Promise(resolve => setTimeout(resolve, delays[2]));
        setSteps(prev => [
          prev[0],
          prev[1],
          { ...prev[2], status: 'done', detail: 'Grounded vector matrix matching complete.', elapsedMs: 5500 },
          { ...prev[3], status: 'active', detail: 'Running final report synthesis (LLM compilation)...', elapsedMs: 7000 }
        ]);

        // 4. synthesis 
        await new Promise(resolve => setTimeout(resolve, delays[3]));
        setSteps(prev => [
          prev[0],
          prev[1],
          prev[2],
          { ...prev[3], status: 'done', detail: 'Technical document compiled successfully.', elapsedMs: 7000 }
        ]);

        const simulatedReport = {
          title: `Deep Research Report: ${trimmed}`,
          introduction: `This comprehensive synthesis examines variables associated with your topic "${trimmed}". Content compiled asynchronously from crawler logs.`,
          sections: [
            {
              sub_question: 'Analysis of key industry paradigms and vectors',
              body: `Current data shows that early iteration stages require rigid validations to prevent drifting. Isomorphic structural parameters enforce compliance under standard execution nodes:
- Deployment vectors use relative links. 
- Inline validations must display warnings to block raw submission, prevent resource choking, and streamline queries.`,
              citations: [{ title: 'Isomorphic Web Core Standard (v2.6)', url: 'https://isomorphic-standard.org' }]
            },
            {
              sub_question: 'Security architectures under multi-tier portals',
              body: `Authentication gateways utilize popup-based handshakes or relative standard oauth setups:
- Redirection parameters should register correctly in preview environments to prevent frame blocking.
- Token caches are kept on credentials panels.`,
              citations: [{ title: 'RFC OAuth relative setups in Sandboxes', url: 'https://oauth.net/2/relative-handshakes' }]
            }
          ],
          conclusion: 'In summary, operational excellence is obtained by combining rigid schema declarations, manual event splitting, and responsive drawer boundaries.',
          persistence: { ok: false, operation_id: 'emulated_research_persisted' }
        };

        setReport(simulatedReport);
        finalMeta = simulatedReport;
        setPersistenceMeta(simulatedReport.persistence);

      } catch (err: any) {
        setSteps(prev => prev.map(s => s.status === 'active' ? { ...s, status: 'failed', detail: err.message } : s));
        setResearchError({
          action: 'deep_research_synthesis',
          reason: err.message || 'Decomposition thread failure'
        });
      } finally {
        setIsStreaming(false);
      }
    } else {
      // actual SSE stream hit
      await fetchSSEStream(
        targetUrl,
        { topic: trimmed },
        {
          onData: (eventData: SSEDataEvent) => {
            // Text data can accumulate in background if needed
            setLoading(false);
            completedText += eventData.text;
          },
          onProgress: (progress: SSEProgressEvent) => {
            setLoading(false);
            // Translate backend progress event phases (decomposition | search | embedding | synthesis)
            const phase = progress.phase.toLowerCase();
            const stepNum = progress.step;
            const desc = progress.detail || '';

            setSteps(prev => {
              const clone = [...prev];
              // Map index by key names matching standard phases
              const phaseIndices: Record<string, number> = {
                decomposition: 0,
                search: 1,
                embedding: 2,
                synthesis: 3
              };

              const activeIdx = phaseIndices[phase];
              if (activeIdx !== undefined) {
                // Done previous steps, activate other steps
                for (let i = 0; i < clone.length; i++) {
                  if (i < activeIdx) {
                    clone[i] = { ...clone[i], status: 'done' };
                  } else if (i === activeIdx) {
                    clone[i] = { ...clone[i], status: 'active', detail: desc, elapsedMs: stepNum * 1000 };
                  } else {
                    clone[i] = { ...clone[i], status: 'pending' };
                  }
                }
              }
              return clone;
            });
          },
          onDone: (done: SSEDoneEvent) => {
            setLoading(false);
            // Finish all steppers on terminal done
            setSteps(prev => prev.map(s => ({ ...s, status: 'done' })));
            
            if (done.report) {
              setReport(done.report);
            }
            finalMeta = done;
            if (done.persistence) {
              setPersistenceMeta(done.persistence);
            }
          },
          onError: (err: SSEErrorEvent) => {
            sError = err;
            setResearchError(err);
            // Mark active step as failed
            setSteps(prev => prev.map(s => s.status === 'active' ? { ...s, status: 'failed', detail: err.reason } : s));
          }
        }
      );
      
      setIsStreaming(false);
      setLoading(false);
    }

    // Capture to persistent history
    if (report || completedText || sError) {
      const histRecord: HistoryRecord = {
        id: `deep_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        projectId: 'deep-research',
        created_at: new Date().toISOString(),
        label: trimmed,
        inputs: { topic: trimmed },
        outputs: {
          text: completedText || undefined,
          metadata: finalMeta || undefined,
          error: sError || undefined
        }
      };

      saveLocalHistoryItem('deep-research', histRecord);
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
        <h2 className="text-xl font-bold font-sans tracking-tight text-white animate-fade-in">Deep Research Portal</h2>
        <p className="text-xs text-text-muted">Generate thorough technical synthesis reports by orchestrating multi-phased web indexing searches and Similarity embedding structures.</p>
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

      {/* Progressive Multi-Tier Stepper panel (Section 5.4) */}
      {(loading || isStreaming) && (
        <Card title="Orchestrator Execution Timeline">
          <div className="flex flex-col gap-4 py-2">
            <ProgressStepper steps={steps} />
            
            {loading && (
              <div className="flex items-center gap-2.5 font-mono text-[11px] text-text-muted animate-pulse mt-2 pl-1 select-none">
                <span className="w-2 h-2 bg-primary-main rounded-full animate-ping" />
                <span>Interrogating index nodes...</span>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Display errors if compile failed */}
      {researchError && (
        <div className="my-1 shrink-0 select-none">
          <ErrorBanner
            action={researchError.action}
            reason={researchError.reason}
          />
        </div>
      )}

      {/* Synthesis report display card */}
      {report && (
        <Card title="Assembled Research Outcomes">
          <div className="flex flex-col gap-6 select-text pt-2.5">
            
            {/* Title & metadata */}
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

            {/* Subsection Collapsibles list */}
            <div className="space-y-4">
              {report.sections?.map((sect: any, sIdx: number) => {
                const isCollapsed = !!collapsedSections[sIdx];
                return (
                  <div key={sIdx} className="border border-border-dim bg-surface-2 bg-opacity-40 rounded-lg overflow-hidden transition-all">
                    
                    {/* Collapsible header */}
                    <div 
                      onClick={() => toggleSection(sIdx)}
                      className="flex items-center justify-between px-5 py-4 cursor-pointer hover:bg-surface-3 transition-colors select-none"
                    >
                      <div className="flex items-start gap-3.5 pr-4">
                        <span className="font-mono text-xs font-bold bg-surface border border-border-dim text-primary-main px-2 py-0.5 rounded shrink-0">
                          Q{sIdx + 1}
                        </span>
                        <h3 className="text-sm font-bold text-white font-sans text-left">
                          {sect.sub_question}
                        </h3>
                      </div>
                      <div className="text-text-faint shrink-0">
                        {isCollapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
                      </div>
                    </div>

                    {/* Collapsible content body */}
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

            {/* Conclusion text banner block */}
            {report.conclusion && (
              <div className="mt-2 bg-primary-main/5 border border-primary-main/15 p-5 rounded-lg border-opacity-70 text-sm select-text">
                <h4 className="font-semibold text-white mb-2 flex items-center gap-1.5 font-sans select-none">
                  <FileText className="w-4 h-4 text-primary-main" />
                  <span>Final Synthesis conclusion</span>
                </h4>
                <p className="text-text-muted leading-relaxed font-sans">{report.conclusion}</p>
              </div>
            )}

            {/* Warning Persistence Chip if relevant */}
            {persistenceMeta && !persistenceMeta.ok && (
              <div className="self-start pt-2 select-none border-t border-border-dim/75 w-full">
                <PersistenceIndicator
                  ok={persistenceMeta.ok}
                  operationId={persistenceMeta.operation_id}
                />
              </div>
            )}

          </div>
        </Card>
      )}

    </div>
  );
};
