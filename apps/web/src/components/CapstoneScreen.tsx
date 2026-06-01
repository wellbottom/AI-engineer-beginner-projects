/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useRef } from 'react';
import { Upload, File, ShieldAlert, Check, X, Award } from 'lucide-react';
import {
  Card,
  Button,
  Textarea,
  StreamingMarkdown,
  ErrorBanner,
  ProgressStep,
  ProgressStepper,
  Badge,
  PersistenceIndicator,
} from './SharedComponents';
import {
  fetchSSEStream,
  SERVICE_URLS,
  PROJECT_ENV_VARS,
  uploadCapstoneDocuments,
} from '../lib/api';
import { HistoryRecord, SSEDataEvent, SSEProgressEvent, SSEDoneEvent, SSEErrorEvent } from '../types';

interface CapstoneScreenProps {
  onAddHistory: (record: HistoryRecord) => void;
}

interface ToolInvocation {
  tool: string;
  ok: boolean;
  error?: string;
}

const INITIAL_STEPS: ProgressStep[] = [
  { label: 'planning', status: 'pending', detail: 'Agent formulates an execution plan' },
  { label: 'tool_invocation', status: 'pending', detail: 'Invoke MCP tools' },
  { label: 'retrieval', status: 'pending', detail: 'Retrieve relevant document chunks' },
  { label: 'answer_synthesis', status: 'pending', detail: 'Synthesize the final answer' },
];

export const CapstoneScreen: React.FC<CapstoneScreenProps> = ({ onAddHistory }) => {
  const [task, setTask] = useState('');

  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [fileUploadError, setFileUploadError] = useState('');
  const [ingestedFiles, setIngestedFiles] = useState<Array<{ filename: string; size?: number }>>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);

  const [steps, setSteps] = useState<ProgressStep[]>(INITIAL_STEPS);

  const [finalAnswer, setFinalAnswer] = useState('');
  const [toolsInvoked, setToolsInvoked] = useState<ToolInvocation[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [stepLimitReached, setStepLimitReached] = useState(false);
  const [persistenceMeta, setPersistenceMeta] = useState<{ ok: boolean; operation_id?: string } | null>(null);

  const [validationError, setValidationError] = useState('');
  const [capstoneError, setCapstoneError] = useState<SSEErrorEvent | null>(null);

  const [dragActive, setDragActive] = useState(false);

  const configured = !!SERVICE_URLS.capstone;

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true);
    else if (e.type === 'dragleave') setDragActive(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      await processFilesAndUpload(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      await processFilesAndUpload(Array.from(e.target.files));
    }
  };

  const processFilesAndUpload = async (filesList: File[]) => {
    setFileUploadError('');

    const MAX_SIZE = 10 * 1024 * 1024; // 10 MB (Requirement 9.5)
    const oversized = filesList.find((f) => f.size > MAX_SIZE);
    if (oversized) {
      setFileUploadError(`File "${oversized.name}" exceeds the maximum allowance of 10MB.`);
      return;
    }

    if (!configured) {
      setFileUploadError(
        `Capstone backend is not configured. Set ${PROJECT_ENV_VARS.capstone} to its base URL.`,
      );
      return;
    }

    setSelectedFiles((prev) => [...prev, ...filesList]);
    setUploadingFiles(true);

    try {
      const ingested = await uploadCapstoneDocuments(filesList);
      setIngestedFiles((prev) => [...prev, ...ingested]);
    } catch (err) {
      setFileUploadError((err as Error).message || 'Document ingestion failed.');
    } finally {
      setUploadingFiles(false);
    }
  };

  const removeFile = (idx: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== idx));
    setIngestedFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleRunTask = async () => {
    if (loading || isStreaming) return;

    const trimmed = task.trim();
    if (!trimmed) {
      setValidationError('Analytical task instruction is required.');
      return;
    }

    setValidationError('');
    setFinalAnswer('');
    setToolsInvoked([]);
    setSources([]);
    setStepLimitReached(false);
    setCapstoneError(null);
    setPersistenceMeta(null);

    const baseUrl = SERVICE_URLS.capstone;
    if (!baseUrl) {
      setCapstoneError({
        action: 'capstone_task',
        reason: `Capstone backend is not configured. Set ${PROJECT_ENV_VARS.capstone} to its base URL.`,
      });
      return;
    }

    setLoading(true);
    setIsStreaming(true);
    setSteps([
      { label: 'planning', status: 'active', detail: 'Agent formulating execution plan...' },
      { label: 'tool_invocation', status: 'pending', detail: 'Awaiting plan' },
      { label: 'retrieval', status: 'pending', detail: 'Awaiting tool results' },
      { label: 'answer_synthesis', status: 'pending', detail: 'Awaiting retrieval' },
    ]);

    let compiledAnswer = '';
    let completedMeta: SSEDoneEvent | null = null;
    let sError: SSEErrorEvent | null = null;

    await fetchSSEStream(
      `${baseUrl}/task`,
      { task: trimmed },
      {
        onData: (eventData: SSEDataEvent) => {
          setLoading(false);
          compiledAnswer += eventData.text;
          setFinalAnswer(compiledAnswer);
        },
        onProgress: (progress: SSEProgressEvent) => {
          setLoading(false);
          const phase = progress.phase.toLowerCase();
          const stepNum = progress.step;
          const desc = progress.detail || '';

          setSteps((prev) => {
            const clone = [...prev];
            const phaseIndices: Record<string, number> = {
              planning: 0,
              tool_invocation: 1,
              retrieval: 2,
              answer_synthesis: 3,
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

          if (done.answer) setFinalAnswer(done.answer);
          if (done.tools_invoked) setToolsInvoked(done.tools_invoked);
          if (done.sources) setSources(done.sources);
          if (done.step_limit_reached !== undefined) setStepLimitReached(done.step_limit_reached);

          completedMeta = done;
          if (done.persistence) setPersistenceMeta(done.persistence);
        },
        onError: (err: SSEErrorEvent) => {
          sError = err;
          setSteps((prev) => prev.map((s) => (s.status === 'active' ? { ...s, status: 'failed', detail: err.reason } : s)));
          setCapstoneError(err);
        },
      },
    );

    setIsStreaming(false);
    setLoading(false);

    const answerText = compiledAnswer || finalAnswer;
    if (answerText || completedMeta || sError) {
      const histRecord: HistoryRecord = {
        id: `caps_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        projectId: 'capstone',
        created_at: new Date().toISOString(),
        label: trimmed,
        inputs: { task: trimmed, documents: ingestedFiles.map((f) => f.filename) },
        outputs: {
          text: answerText || undefined,
          metadata: completedMeta || undefined,
          error: sError || undefined,
        },
      };
      onAddHistory(histRecord);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">

      {/* Parameters & Multi-file ingest zone on Left (5 columns) */}
      <div className="lg:col-span-5 flex flex-col gap-5 select-none">

        <Card title="Task Description">
          <div className="flex flex-col gap-4">
            <Textarea
              id="capstone-task-input-text"
              label="Analytical Agent Prompt"
              placeholder="Structure your multi-tool query, e.g. 'Read the ingested manuals and extract the core constraints'..."
              value={task}
              onChange={(e) => setTask(e.target.value)}
              disabled={loading || isStreaming}
              error={validationError}
              maxLength={2000}
              mono
              className="min-h-[82px]"
            />

            <Button
              variant="primary"
              onClick={handleRunTask}
              disabled={loading || isStreaming || !task.trim()}
              isLoading={loading || isStreaming}
              className="w-full gap-2 text-xs font-semibold py-5"
            >
              <Award className="w-4 h-4 shrink-0" />
              <span>Run Multi-Tool Task</span>
            </Button>
          </div>
        </Card>

        <Card title="Document Context Ingestion">
          <div className="flex flex-col gap-4">

            <div
              onDragEnter={handleDrag}
              onDragOver={handleDrag}
              onDragLeave={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-lg p-6 py-8 text-center transition-all cursor-pointer select-none ${dragActive ? 'border-primary-main bg-primary-main/10' : 'border-border-dim bg-bg hover:border-border-strong hover:bg-surface-2'}`}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileInput}
                disabled={uploadingFiles || loading || isStreaming}
                className="hidden"
                accept=".txt,.pdf,.csv,.doc,.docx,.json"
              />

              <div className="flex flex-col items-center gap-2">
                <div className="p-3 border border-border-dim bg-surface rounded-full text-text-muted">
                  <Upload className="w-5 h-5" />
                </div>
                <span className="text-xs font-semibold text-text-main">
                  {uploadingFiles ? 'Uploading documents...' : 'Ingest a reference document'}
                </span>
                <span className="text-[10px] text-text-faint font-mono">
                  Drag files here or click (txt, pdf, JSON &bull; ≤10MB each)
                </span>
              </div>
            </div>

            {fileUploadError && (
              <div className="border border-danger-subtle/20 bg-danger-bg/40 rounded p-3 text-xs leading-relaxed text-danger-subtle flex gap-2">
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{fileUploadError}</span>
              </div>
            )}

            {selectedFiles.length > 0 && (
              <div className="flex flex-col gap-2">
                <span className="text-[10px] font-mono font-bold tracking-wider text-text-faint uppercase">
                  Engaged files ({selectedFiles.length})
                </span>

                <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto">
                  {selectedFiles.map((file, idx) => {
                    const isIngested = !!ingestedFiles[idx];
                    const sizeMB = (file.size / (1024 * 1024)).toFixed(2);

                    return (
                      <div key={idx} className="flex justify-between items-center bg-surface-2 px-3 py-2 border border-border-dim rounded-md text-xs group">
                        <div className="flex items-center gap-2 min-w-0 flex-1 pr-4">
                          <File className="w-3.5 h-3.5 text-text-muted shrink-0" />
                          <span className="font-mono text-text-main truncate select-all">{file.name}</span>
                          <span className="text-[10px] text-text-faint font-mono font-normal flex-shrink-0">({sizeMB} MB)</span>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          {isIngested ? (
                            <span className="text-[10px] text-accent-subtle font-mono font-bold flex items-center gap-1">
                              <Check className="w-3 h-3" /> Ingested
                            </span>
                          ) : (
                            <span className="text-[10px] text-text-faint font-mono animate-pulse">Syncing...</span>
                          )}

                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              removeFile(idx);
                            }}
                            disabled={loading || isStreaming}
                            className="text-text-faint hover:text-danger-subtle rounded p-0.5 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

          </div>
        </Card>

      </div>

      {/* Orchestrator progress, answers and metrics on Right (7 columns) */}
      <div className="lg:col-span-7 flex flex-col gap-5">

        {(loading || isStreaming) && (
          <Card title="Agent Execution steps">
            <div className="flex flex-col gap-2">
              <ProgressStepper steps={steps} />
            </div>
          </Card>
        )}

        {capstoneError && (
          <div className="my-1 shrink-0">
            <ErrorBanner action={capstoneError.action} reason={capstoneError.reason} />
          </div>
        )}

        {(finalAnswer || toolsInvoked.length > 0 || sources.length > 0) && (
          <div className="flex flex-col gap-5 select-text">

            <Card title="Synthesized Task Solutions">
              <div className="flex flex-col gap-4">

                {stepLimitReached && (
                  <div className="border border-yellow-500/10 bg-yellow-500/5 text-yellow-400 p-3.5 rounded-md flex gap-2.5 text-xs font-sans select-none">
                    <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                    <div>
                      <h4 className="font-semibold text-white">Step limit reached</h4>
                      <p className="text-text-muted text-[11px] mt-0.5">The agent hit the 25-step limit. The output below reflects the results gathered so far.</p>
                    </div>
                  </div>
                )}

                <div className="min-h-[140px] whitespace-pre-wrap leading-relaxed max-h-[500px] overflow-y-auto bg-surface-2 bg-opacity-20 border border-border-dim/50 rounded-lg p-5">
                  <StreamingMarkdown content={finalAnswer} isStreaming={isStreaming} />
                </div>

                {sources.length > 0 && (
                  <div className="mt-4 border-t border-border-dim pt-4 shrink-0 select-none">
                    <h4 className="text-[10px] font-mono font-bold tracking-wider text-text-faint uppercase mb-2">Sources Referenced:</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {sources.map((src, sIdx) => (
                        <span key={sIdx} className="bg-surface-2 border border-border-dim text-xs font-mono font-medium text-text-muted px-2 py-0.5 rounded">
                          {src}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {persistenceMeta && !persistenceMeta.ok && (
                  <div className="self-start pt-2 select-none">
                    <PersistenceIndicator ok={persistenceMeta.ok} operationId={persistenceMeta.operation_id} />
                  </div>
                )}

              </div>
            </Card>

            {toolsInvoked.length > 0 && (
              <Card title="Invoked MCP Tools">
                <div className="flex flex-col gap-2 max-h-52 overflow-y-auto">
                  {toolsInvoked.map((t, tIdx) => (
                    <div key={tIdx} className="flex justify-between items-center bg-surface-2 px-3.5 py-2.5 border border-border-dim rounded-md text-xs">
                      <span className="font-mono text-text-main font-semibold select-all">{t.tool}</span>

                      <div className="shrink-0">
                        {t.ok ? (
                          <Badge variant="success">OK</Badge>
                        ) : (
                          <div className="flex flex-col items-end gap-1 select-none">
                            <Badge variant="danger">Failed</Badge>
                            {t.error && <span className="text-[10px] font-mono text-danger-subtle font-normal">{t.error}</span>}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

          </div>
        )}

      </div>

    </div>
  );
};
