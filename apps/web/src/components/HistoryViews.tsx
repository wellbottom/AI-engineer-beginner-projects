/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { 
  FolderOpen, 
  Trash2, 
  ArrowLeft, 
  Clock, 
  User, 
  Cpu, 
  Grid,
  FileCheck,
  AlertTriangle
} from 'lucide-react';
import { HistoryRecord, ProjectId } from '../types';
import { 
  Card, 
  Badge, 
  Button, 
  StreamingMarkdown, 
  TokenUsage, 
  CitationList, 
  ProgressStep,
  ProgressStepper,
  ErrorBanner
} from './SharedComponents';

// Simple time utility formatter 
export function formatRelativeTime(isoString: string): string {
  try {
    const diff = Date.now() - new Date(isoString).getTime();
    if (diff < 60000) return 'Just now';
    
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch (e) {
    return 'Recently';
  }
}

interface HistoryListProps {
  projectId: ProjectId;
  records: HistoryRecord[];
  onSelect: (recordId: string) => void;
  onDelete?: (recordId: string) => void;
}

export const HistoryList: React.FC<HistoryListProps> = ({
  records,
  onSelect,
  onDelete
}) => {
  if (records.length === 0) {
    return (
      <Card className="flex flex-col items-center justify-center text-center py-12 px-6">
        <FolderOpen className="w-12 h-12 text-text-faint mb-3" />
        <h3 className="text-md font-semibold text-text-main">
          No history captured yet
        </h3>
        <p className="text-xs text-text-muted max-w-sm mt-1 mb-4 leading-relaxed font-sans">
          Execute an active prompt, search query, or research build task to create a persistent log.
        </p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-semibold font-mono text-text-faint uppercase tracking-wider">
          Historic Logs ({records.length})
        </span>
      </div>

      <div className="flex flex-col gap-2">
        {records.map(record => (
          <div
            key={record.id}
            onClick={() => onSelect(record.id)}
            className="group flex items-center justify-between bg-surface border border-border-dim rounded-md px-4 py-3 hover:border-border-strong hover:bg-surface-2 transition-all cursor-pointer shadow-sm select-none"
          >
            <div className="flex items-center gap-3.5 min-w-0 flex-1">
              {/* Type / source visualization badge */}
              <div className="p-1.5 bg-surface-2 group-hover:bg-surface-3 rounded text-primary-main shrink-0">
                <Clock className="w-4 h-4 text-text-muted group-hover:text-primary-main" />
              </div>
              
              <div className="min-w-0 flex-1">
                <p className="text-sm font-sans font-medium text-text-main truncate pr-2">
                  {record.label || 'Empty query label'}
                </p>
                <div className="flex items-center gap-2 mt-1 text-[11px] text-text-faint font-mono">
                  <span>{formatRelativeTime(record.created_at)}</span>
                  <span>&bull;</span>
                  <span>{new Date(record.created_at).toLocaleString()}</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3 pr-1">
              {record.outputs.error ? (
                <Badge variant="danger">Failed</Badge>
              ) : (
                <Badge variant="success">Completed</Badge>
              )}

              {onDelete && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(record.id);
                  }}
                  title="Remove history record"
                  className="p-1.5 text-text-faint hover:text-danger-subtle hover:bg-danger-subtle/10 rounded cursor-pointer transition-colors opacity-0 group-hover:opacity-100"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ==========================================
// HISTORY DETAIL / VIEW REUSER CARD
// ==========================================
interface HistoryViewDetailProps {
  projectId: ProjectId;
  record: HistoryRecord;
  onBack: () => void;
}

export const HistoryViewDetail: React.FC<HistoryViewDetailProps> = ({
  projectId,
  record,
  onBack
}) => {
  const metadata = record.outputs.metadata;

  return (
    <div className="flex flex-col gap-6">
      
      {/* Detail Header link */}
      <div className="flex items-center justify-between select-none">
        <Button variant="ghost" onClick={onBack} className="pl-1.5 text-xs text-text-muted hover:text-white shrink-0">
          <ArrowLeft className="w-3.5 h-3.5 mr-2" />
          <span>Back to History list</span>
        </Button>
        <span className="text-xs font-mono text-text-faint">
          Logged {new Date(record.created_at).toLocaleString()}
        </span>
      </div>

      {record.outputs.error && (
        <ErrorBanner 
          action={record.outputs.error.action} 
          reason={record.outputs.error.reason} 
        />
      )}

      {/* RENDER IN HIGH FIDELITY REUSER COMPONENTS PER THE STATE MATRIX */}
      {projectId === 'playground' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* inputs */}
          <div className="lg:col-span-5 flex flex-col gap-4">
            <Card title="Input Parameters">
              <div className="flex flex-col gap-3 font-mono text-xs">
                {record.inputs.model && (
                  <div className="flex justify-between border-b border-border-dim pb-1.5">
                    <span className="text-text-faint">Target model:</span>
                    <span className="text-white font-medium">{record.inputs.model}</span>
                  </div>
                )}
                {record.inputs.temperature !== undefined && (
                  <div className="flex justify-between border-b border-border-dim pb-1.5">
                    <span className="text-text-faint">Temperature:</span>
                    <span className="text-white font-medium">{record.inputs.temperature}</span>
                  </div>
                )}
                {record.inputs.max_tokens !== undefined && (
                  <div className="flex justify-between border-b border-border-dim pb-1.5">
                    <span className="text-text-faint">Max Tokens limit:</span>
                    <span className="text-white font-medium">{record.inputs.max_tokens}</span>
                  </div>
                )}
                {record.inputs.system_prompt && (
                  <div className="flex flex-col gap-1 pt-1">
                    <span className="text-text-faint">System Prompt directive:</span>
                    <div className="bg-surface-2 p-2.5 rounded font-sans text-xs text-text-muted whitespace-pre-wrap max-h-32 overflow-y-auto border border-border-dim">
                      {record.inputs.system_prompt}
                    </div>
                  </div>
                )}
              </div>
            </Card>

            <Card title="Source Prompt">
              <div className="bg-surface-2 p-3 border border-border-dim rounded font-mono text-xs text-white max-h-48 overflow-y-auto whitespace-pre-wrap">
                {record.inputs.prompt}
              </div>
            </Card>
          </div>

          {/* output content */}
          <div className="lg:col-span-7 flex flex-col gap-4">
            <Card title="Target Generated Output">
              <div className="flex flex-col gap-4 min-h-[150px]">
                {record.outputs.text ? (
                  <StreamingMarkdown content={record.outputs.text} isStreaming={false} />
                ) : (
                  <span className="text-xs text-text-faint italic">No incremental content captured.</span>
                )}
                
                {metadata?.usage && (
                  <div className="mt-4 border-t border-border-dim pt-4">
                    <TokenUsage 
                      promptTokens={metadata.usage.prompt_tokens} 
                      outputTokens={metadata.usage.output_tokens} 
                      totalTokens={metadata.usage.total_tokens} 
                    />
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}

      {projectId === 'support' && (
        <div className="max-w-3xl mx-auto w-full flex flex-col gap-4">
          <Card title="Chat History Summary">
            <div className="flex flex-col gap-4 max-h-[500px] overflow-y-auto pr-2">
              <div className="flex flex-col gap-1.5 items-end self-end max-w-[85%]">
                <span className="text-[10px] font-mono text-text-faint flex items-center gap-1">
                  <User className="w-3 h-3" /> User
                </span>
                <div className="bg-surface-3 text-text-main px-4 py-2.5 rounded-lg text-sm rounded-tr-none font-sans border border-border-dim">
                  {record.inputs.message}
                </div>
              </div>

              {record.outputs.text && (
                <div className="flex flex-col gap-1.5 items-start max-w-[85%]">
                  <span className="text-[10px] font-mono text-primary-main flex items-center gap-1">
                    <Cpu className="w-3 h-3" /> Assistant Agent
                  </span>
                  <div className="bg-surface-2 text-text-main px-4 py-2.5 rounded-lg text-sm rounded-tl-none font-sans border border-border-dim">
                    <StreamingMarkdown content={record.outputs.text} isStreaming={false} />
                  </div>
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {projectId === 'web-agent' && (
        <div className="max-w-4xl mx-auto w-full flex flex-col gap-4">
          <Card title="Search & Retrieval Summary">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-text-faint">Web query context:</span>
                <p className="text-sm text-white font-mono bg-surface-2 p-3 rounded border border-border-dim">
                  {record.inputs.question}
                </p>
              </div>

              <div className="h-px bg-border-dim my-3" />

              <div className="flex flex-col gap-3 min-h-[120px]">
                <h4 className="text-xs font-semibold text-text-faint">Synthesized direct response:</h4>
                {record.outputs.text ? (
                  <StreamingMarkdown content={record.outputs.text} isStreaming={false} />
                ) : (
                  <span className="text-xs text-text-faint italic">No content retrieved.</span>
                )}

                {metadata?.citations && metadata.citations.length > 0 && (
                  <div className="mt-4 border-t border-border-dim pt-4">
                    <CitationList citations={metadata.citations} />
                  </div>
                )}
              </div>
            </div>
          </Card>
        </div>
      )}

      {projectId === 'deep-research' && (
        <div className="max-w-4xl mx-auto w-full flex flex-col gap-6">
          <Card title="Synthesized Deep Report">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-text-faint">Deep Topic explored:</span>
                <p className="text-sm font-semibold font-sans text-white border-l-2 border-primary-main pl-3 my-1">
                  {record.inputs.topic}
                </p>
              </div>

              <div className="h-px bg-border-dim my-2" />

              {metadata?.report ? (
                <div className="flex flex-col gap-6 pt-2 select-text">
                  <h1 className="text-2xl font-bold font-sans tracking-tight text-white">
                    {metadata.report.title || 'Untitled Synthesis Report'}
                  </h1>
                  
                  {metadata.report.introduction && (
                    <p className="text-sm text-text-muted leading-relaxed font-sans first-letter:text-2xl first-letter:float-left first-letter:mr-1">
                      {metadata.report.introduction}
                    </p>
                  )}

                  <div className="space-y-6 mt-4">
                    {metadata.report.sections?.map((sect: any, sIdx: number) => (
                      <div key={sIdx} className="border border-border-dim bg-surface-2 rounded-lg p-5">
                        <h3 className="text-md font-semibold text-white mb-2 flex items-center gap-2">
                          <span className="font-mono text-primary-main text-xs font-bold bg-surface-3 px-2 py-0.5 rounded">Q{sIdx+1}</span>
                          {sect.sub_question}
                        </h3>
                        <p className="text-sm font-sans text-text-main leading-relaxed whitespace-pre-line">{sect.body}</p>
                        {sect.citations && sect.citations.length > 0 && (
                          <div className="mt-4 border-t border-border-dim pt-3">
                            <CitationList citations={sect.citations} />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {metadata.report.conclusion && (
                    <div className="mt-4 bg-primary-main/5 border border-primary-main/10 rounded-lg p-5">
                      <h4 className="text-sm font-semibold text-white mb-2">Final Summary & Conclusions</h4>
                      <p className="text-sm text-text-muted leading-relaxed font-sans">{metadata.report.conclusion}</p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-8 border border-dashed border-border-dim rounded flex flex-col items-center">
                  <span className="text-xs text-text-faint italic font-mono mb-2">Detailed report contents missing.</span>
                  {record.outputs.text && (
                    <StreamingMarkdown content={record.outputs.text} isStreaming={false} />
                  )}
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {projectId === 'image' && (
        <div className="max-w-3xl mx-auto w-full flex flex-col gap-6">
          <Card title="Rendered Image Result">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1 text-xs">
                <span className="text-text-faint font-medium">Prompt used:</span>
                <p className="text-sm text-white font-mono bg-surface-2 p-3 rounded border border-border-dim">
                  {record.inputs.prompt}
                </p>
              </div>

              {record.outputs.imageUrl ? (
                <div className="border border-border-strong bg-surface-2 rounded-lg overflow-hidden flex items-center justify-center max-w-full my-3">
                  <img
                    src={record.outputs.imageUrl}
                    alt={record.inputs.prompt}
                    referrerPolicy="no-referrer"
                    className="max-h-[450px] object-contain rounded w-full h-auto"
                  />
                </div>
              ) : (
                <div className="border border-dashed border-border-dim rounded-lg p-12 text-center text-xs italic text-text-faint">
                  Rendered art binary is missing
                </div>
              )}

              {record.inputs.model && (
                <div className="flex justify-between text-xs font-mono text-text-faint">
                  <span>Generator Engine:</span>
                  <span className="text-text-main font-semibold">{record.inputs.model}</span>
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {projectId === 'capstone' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* inputs / uploaded metadata */}
          <div className="lg:col-span-5 flex flex-col gap-4">
            <Card title="Task context">
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-text-faint font-semibold">User task command:</span>
                  <div className="bg-surface-2 p-3 font-mono text-xs border border-border-dim rounded whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {record.inputs.task}
                  </div>
                </div>

                {record.inputs.documents && record.inputs.documents.length > 0 && (
                  <div className="flex flex-col gap-1.5 pt-1">
                    <span className="text-xs text-text-faint font-semibold flex items-center gap-1.5">
                      <FileCheck className="w-3.5 h-3.5 text-primary-main" /> Ingested Files:
                    </span>
                    <div className="flex flex-col gap-1.5 max-h-32 overflow-y-auto">
                      {record.inputs.documents.map((docName: string, dIdx: number) => (
                        <div key={dIdx} className="flex justify-between items-center bg-surface-2 px-2.5 py-1.5 border border-border-dim rounded text-xs">
                          <span className="font-mono text-text-muted truncate select-all">{docName}</span>
                          <span className="text-text-faint text-[10px]">Ingested</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Card>

            {metadata?.tools_invoked && metadata.tools_invoked.length > 0 && (
              <Card title="Tools Executed">
                <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
                  {metadata.tools_invoked.map((t: any, idx: number) => (
                    <div key={idx} className="flex items-center justify-between bg-surface-2 text-xs border border-border-dim rounded p-2">
                      <span className="font-mono text-text-main font-medium">{t.tool}</span>
                      {t.ok ? (
                        <Badge variant="success">OK</Badge>
                      ) : (
                        <div className="flex flex-col items-end gap-0.5">
                          <Badge variant="danger">Error</Badge>
                          {t.error && <span className="text-[10px] text-danger-subtle font-mono">{t.error}</span>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>

          {/* final answer and tools */}
          <div className="lg:col-span-7 flex flex-col gap-4">
            <Card title="Consolidated Task Solutions">
              <div className="flex flex-col gap-4">
                {metadata?.step_limit_reached && (
                  <div className="flex items-center gap-2 border border-yellow-500/10 bg-yellow-500/5 text-yellow-400 p-3 rounded text-xs font-sans">
                    <AlertTriangle className="w-4 h-4 shrink-0" />
                    <span>Recursive execution step limit (25 steps) reached. Output may be incomplete.</span>
                  </div>
                )}

                <div className="min-h-[150px]">
                  {metadata?.answer ? (
                    <StreamingMarkdown content={metadata.answer} isStreaming={false} />
                  ) : record.outputs.text ? (
                    <StreamingMarkdown content={record.outputs.text} isStreaming={false} />
                  ) : (
                    <span className="text-xs text-text-faint italic">No final output answer was synthesized.</span>
                  )}
                </div>

                {metadata?.sources && metadata.sources.length > 0 && (
                  <div className="mt-4 border-t border-border-dim pt-4">
                    <h4 className="text-xs font-semibold text-text-faint uppercase mb-2">Sources Referenced</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {metadata.sources.map((src: string, idx: number) => (
                        <span key={idx} className="text-xs bg-surface-2 border border-border-dim rounded px-2 py-0.5 font-mono text-text-muted">
                          {src}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}

    </div>
  );
};
