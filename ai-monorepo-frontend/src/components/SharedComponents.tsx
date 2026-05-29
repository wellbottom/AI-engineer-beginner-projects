/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { motion } from 'motion/react';
import { 
  AlertTriangle, 
  ExternalLink, 
  CheckCircle, 
  Play, 
  Loader2, 
  AlertCircle, 
  Info,
  Clock
} from 'lucide-react';
import Markdown from 'react-markdown';
import { SSEProgressEvent } from '../types';

// ==========================================
// BUTTON COMPONENT
// ==========================================
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  isLoading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  isLoading = false,
  className = '',
  disabled,
  ...props
}) => {
  const baseStyle = "inline-flex items-center justify-center font-medium font-sans rounded-md transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-offset-2 focus:ring-offset-[var(--bg)] disabled:opacity-45 disabled:pointer-events-none text-sm h-[38px] px-4 cursor-pointer";
  
  const variants = {
    primary: "bg-primary-main text-primary-contrast hover:bg-primary-hover",
    secondary: "bg-surface-2 text-text-main border border-border-dim hover:bg-surface-3",
    ghost: "bg-transparent text-text-muted hover:bg-surface-2 hover:text-text-main",
    danger: "bg-danger-subtle text-white hover:bg-opacity-90",
  };

  return (
    <button
      className={`${baseStyle} ${variants[variant]} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <>
          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          <span>Please wait...</span>
        </>
      ) : (
        children
      )}
    </button>
  );
};

// ==========================================
// CARD COMPONENT
// ==========================================
interface CardProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: React.ReactNode;
  headerAction?: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  children,
  title,
  headerAction,
  className = '',
  ...props
}) => {
  return (
    <div
      className={`bg-surface border border-border-dim rounded-lg p-5 sm:p-6 shadow-sm transition-all duration-200 ${className}`}
      {...props}
    >
      {title && (
        <div className="flex items-center justify-between border-b border-border-dim pb-4 mb-4">
          <h2 className="text-lg font-semibold font-sans tracking-tight text-text-main">
            {title}
          </h2>
          {headerAction && <div className="flex items-center">{headerAction}</div>}
        </div>
      )}
      {children}
    </div>
  );
};

// ==========================================
// INPUTS & COMPONENTS
// ==========================================
interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  mono?: boolean;
}

export const Input: React.FC<InputProps> = ({
  label,
  error,
  mono = false,
  className = '',
  id,
  ...props
}) => {
  return (
    <div className="w-full flex flex-col gap-1.5">
      {label && (
        <label htmlFor={id} className="text-xs font-medium text-text-muted">
          {label}
        </label>
      )}
      <input
        id={id}
        className={`bg-surface-2 border ${error ? 'border-danger-subtle' : 'border-border-dim'} focus:border-border-strong text-text-main placeholder-text-faint hover:border-border-strong rounded-sm px-3 py-2 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-offset-2 focus:ring-offset-[var(--bg)] ${mono ? 'font-mono' : 'font-sans'} ${className}`}
        {...props}
      />
      {error && <span className="text-xs text-danger-subtle font-medium">{error}</span>}
    </div>
  );
};

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  mono?: boolean;
  maxLength?: number;
}

export const Textarea: React.FC<TextareaProps> = ({
  label,
  error,
  mono = false,
  maxLength,
  className = '',
  value = '',
  id,
  onChange,
  ...props
}) => {
  const currentLength = typeof value === 'string' ? value.length : 0;
  const isOverLimit = maxLength ? currentLength > maxLength : false;

  return (
    <div className="w-full flex flex-col gap-1.5 relative">
      {label && (
        <label htmlFor={id} className="text-xs font-medium text-text-muted">
          {label}
        </label>
      )}
      <textarea
        id={id}
        maxLength={maxLength}
        value={value}
        onChange={onChange}
        className={`bg-surface-2 border ${error || isOverLimit ? 'border-danger-subtle' : 'border-border-dim'} focus:border-border-strong text-text-main placeholder-text-faint hover:border-border-strong rounded-sm px-3 py-2 text-sm transition-colors min-h-[100px] resize-y focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-offset-2 focus:ring-offset-[var(--bg)] ${mono ? 'font-mono' : 'font-sans'} ${className}`}
        {...props}
      />
      
      <div className="flex justify-between items-center mt-1">
        <div>
          {error && <span className="text-xs text-danger-subtle font-medium">{error}</span>}
        </div>
        {maxLength && (
          <span className={`text-[11px] font-mono self-end ${isOverLimit ? 'text-danger-subtle font-bold' : 'text-text-faint'}`}>
            {currentLength}/{maxLength}
          </span>
        )}
      </div>
    </div>
  );
};

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: { value: string; label: string }[];
  error?: string;
}

export const Select: React.FC<SelectProps> = ({
  label,
  options,
  error,
  className = '',
  id,
  ...props
}) => {
  return (
    <div className="w-full flex flex-col gap-1.5">
      {label && (
        <label htmlFor={id} className="text-xs font-medium text-text-muted">
          {label}
        </label>
      )}
      <select
        id={id}
        className={`bg-surface-2 border cursor-pointer ${error ? 'border-danger-subtle' : 'border-border-dim'} focus:border-border-strong text-text-main hover:border-border-strong rounded-sm px-3 py-2 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-offset-2 focus:ring-offset-[var(--bg)] ${className}`}
        {...props}
      >
        {options.map(opt => (
          <option key={opt.value} value={opt.value} className="bg-surface text-text-main">
            {opt.label}
          </option>
        ))}
      </select>
      {error && <span className="text-xs text-danger-subtle font-medium">{error}</span>}
    </div>
  );
};

// ==========================================
// BADGE COMPONENT
// ==========================================
export type BadgeVariant = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'neutral',
  className = ''
}) => {
  const styles = {
    neutral: "bg-surface-3 text-text-muted border border-border-dim",
    success: "bg-[rgba(70,212,179,0.1)] text-accent-subtle border border-[rgba(70,212,179,0.25)]",
    warning: "bg-[rgba(242,117,68,0.1)] text-warning-subtle border border-[rgba(242,117,68,0.25)]",
    danger: "bg-[rgba(255,107,107,0.1)] text-danger-subtle border border-[rgba(255,107,107,0.25)]",
    info: "bg-[rgba(109,139,255,0.1)] text-primary-main border border-[rgba(109,139,255,0.25)]"
  };

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold font-mono tracking-wide ${styles[variant]} ${className}`}>
      {children}
    </span>
  );
};

// ==========================================
// LOADING INDICATOR
// ==========================================
interface LoadingIndicatorProps {
  label?: string;
}

export const LoadingIndicator: React.FC<LoadingIndicatorProps> = ({
  label = 'Loading...'
}) => {
  return (
    <div className="flex items-center gap-3 py-3 border border-border-dim bg-surface rounded-lg px-4 w-fit select-none animate-pulse">
      <Loader2 className="w-4 h-4 text-primary-main animate-spin shrink-0" />
      <span className="text-xs font-sans text-text-muted">{label}</span>
    </div>
  );
};

// Skeleton loading lists 
export const SkeletonHistoryRows: React.FC = () => {
  return (
    <div className="flex flex-col gap-2.5">
      {[1, 2, 3, 4].map(idx => (
        <div key={idx} className="bg-surface border border-border-dim h-[56px] rounded-md animate-pulse flex items-center justify-between px-4">
          <div className="flex flex-col gap-1.5 w-2/3">
            <div className="h-3.5 bg-surface-3 rounded w-3/4"></div>
            <div className="h-2.5 bg-surface-3 rounded w-1/4"></div>
          </div>
          <div className="h-4 bg-surface-3 rounded w-16"></div>
        </div>
      ))}
    </div>
  );
};

// ==========================================
// STREAMING MARKDOWN WITH CARET
// ==========================================
interface StreamingMarkdownProps {
  content: string;
  isStreaming?: boolean;
}

export const StreamingMarkdown: React.FC<StreamingMarkdownProps> = ({
  content,
  isStreaming = false
}) => {
  return (
    <div className="markdown-body font-sans text-sm text-text-main leading-relaxed space-y-4">
      <Markdown
        components={{
          h1: ({ children }) => <h1 className="text-lg font-bold text-text-main border-b border-border-dim pb-2 mt-4">{children}</h1>,
          h2: ({ children }) => <h2 className="text-md font-bold text-text-main mt-3">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-bold text-text-main mt-2">{children}</h3>,
          p: ({ children }) => <p className="mb-3 break-words">{children}</p>,
          ul: ({ children }) => <ul className="list-disc pl-5 mb-3 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 mb-3 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="mb-0.5">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-text-main">{children}</strong>,
          em: ({ children }) => <em className="italic text-text-muted">{children}</em>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-primary-main pl-3 italic text-text-muted bg-surface-2 py-1 px-2 my-2 rounded-r-sm">
              {children}
            </blockquote>
          ),
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '');
            const inline = !match;
            return inline ? (
              <code className="bg-surface-3 text-primary-main px-1 py-0.5 rounded font-mono text-xs" {...props}>
                {children}
              </code>
            ) : (
              <div className="group relative my-3">
                <div className="flex items-center justify-between bg-surface-3 px-4 py-1.5 text-xs text-text-muted rounded-t border-t border-x border-border-dim font-mono">
                  <span>{match[1].toLowerCase()}</span>
                </div>
                <pre className="overflow-x-auto bg-surface-2 p-4 text-xs font-mono border border-border-dim rounded-b shadow-inner">
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              </div>
            );
          }
        }}
      >
        {content}
      </Markdown>
      {isStreaming && (
        <span className="inline-block translate-y-0.5 ml-0.5 text-accent-subtle font-bold text-lg caret-blink">
          ▍
        </span>
      )}
    </div>
  );
};

// ==========================================
// ERROR BANNER
// ==========================================
interface ErrorBannerProps {
  action: string;
  reason: string;
  onRetry?: () => void;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({
  action,
  reason,
  onRetry
}) => {
  return (
    <div role="alert" className="flex flex-col sm:flex-row sm:items-center justify-between border-l-4 border-danger-subtle bg-danger-bg rounded-md p-4 bg-opacity-40 gap-4 max-w-full">
      <div className="flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-danger-subtle shrink-0 mt-0.5" />
        <div>
          <h3 className="text-sm font-semibold font-sans text-white capitalize">
            {action ? action.replace(/_/g, ' ') : 'Action'} Failed
          </h3>
          <p className="text-xs font-sans text-text-muted mt-1 leading-relaxed">
            {reason || 'An unexpected error occurred. Please try again.'}
          </p>
        </div>
      </div>
      {onRetry && (
        <Button
          variant="secondary"
          onClick={onRetry}
          className="text-xs h-8 px-3 shrink-0 py-1 bg-surface hover:bg-surface-2 text-text-main border border-border-dim rounded"
        >
          Retry Code Run
        </Button>
      )}
    </div>
  );
};

// ==========================================
// CITATION LIST
// ==========================================
interface Citation {
  url: string;
  title: string;
}

interface CitationListProps {
  citations: Citation[];
}

export const CitationList: React.FC<CitationListProps> = ({ citations }) => {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-4 flex flex-col gap-2">
      <h4 className="text-xs font-semibold text-text-faint tracking-wider uppercase">
        Web Sources & Citations:
      </h4>
      <div className="flex flex-wrap gap-2">
        {citations.map((cite, idx) => {
          let domain = 'source';
          try {
            domain = new URL(cite.url).hostname.replace('www.', '');
          } catch (e) {}

          return (
            <a
              key={idx}
              href={cite.url}
              target="_blank"
              referrerPolicy="no-referrer"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 bg-surface-2 border border-border-dim text-xs font-sans text-text-muted px-2.5 py-1 rounded hover:bg-surface-3 transition-colors group cursor-pointer"
            >
              <span className="font-mono text-primary-main font-semibold">[{idx + 1}]</span>
              <span className="truncate max-w-[150px]">{cite.title || domain}</span>
              <ExternalLink className="w-3 h-3 text-text-faint group-hover:text-primary-main rounded" />
            </a>
          );
        })}
      </div>
    </div>
  );
};

// ==========================================
// TOKEN USAGE ROW
// ==========================================
interface TokenUsageProps {
  promptTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
}

export const TokenUsage: React.FC<TokenUsageProps> = ({
  promptTokens,
  outputTokens,
  totalTokens
}) => {
  if (promptTokens === undefined && outputTokens === undefined && totalTokens === undefined) return null;

  return (
    <div className="flex items-center gap-3 border border-border-dim bg-surface rounded px-3 py-1.5 w-fit">
      <Clock className="w-3.5 h-3.5 text-text-muted" />
      <span className="text-[11px] font-mono whitespace-nowrap text-text-muted select-none">
        prompt <span className="text-text-main font-semibold">{promptTokens ?? '?'}</span>
        {' '}&middot;{' '}
        output <span className="text-text-main font-semibold">{outputTokens ?? '?'}</span>
        {' '}&middot;{' '}
        total <span className="text-text-main font-semibold">{totalTokens ?? (promptTokens && outputTokens ? (promptTokens + outputTokens) : '?')}</span>
      </span>
    </div>
  );
};

// ==========================================
// PROGRESS STEPPER
// ==========================================
export type StepStatus = 'pending' | 'active' | 'done' | 'failed';

export interface ProgressStep {
  label: string;
  status: StepStatus;
  detail?: string;
  elapsedMs?: number;
}

interface ProgressStepperProps {
  steps: ProgressStep[];
}

export const ProgressStepper: React.FC<ProgressStepperProps> = ({ steps }) => {
  return (
    <div className="flex flex-col gap-4 py-2 relative">
      {/* Connector line */}
      <div className="absolute left-[9px] top-4 bottom-4 w-0.5 bg-border-dim z-0" />

      {steps.map((step, idx) => {
        const circleColors = {
          pending: "border-border-strong bg-bg text-text-faint",
          active: "border-primary-main bg-bg text-primary-main ring-2 ring-[rgba(109,139,255,0.2)]",
          done: "border-accent-subtle bg-bg text-accent-subtle",
          failed: "border-danger-subtle bg-bg text-danger-subtle"
        };

        const titleColors = {
          pending: "text-text-faint",
          active: "text-primary-main font-medium",
          done: "text-text-main",
          failed: "text-danger-subtle"
        };

        return (
          <div key={idx} className="flex gap-4 items-start select-none z-10">
            <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 font-mono text-[9px] font-bold ${circleColors[step.status]}`}>
              {step.status === 'done' ? (
                <span>&bull;</span>
              ) : step.status === 'failed' ? (
                <span>&times;</span>
              ) : step.status === 'active' ? (
                <div className="w-1.5 h-1.5 bg-primary-main rounded-full animate-ping" />
              ) : (
                <span>{idx + 1}</span>
              )}
            </div>

            <div className="flex flex-col gap-0.5 pt-0.5">
              <div className="flex items-center gap-2">
                <span className={`text-xs font-sans capitalize ${titleColors[step.status]}`}>
                  {step.label}
                </span>
                {step.elapsedMs !== undefined && (
                  <span className="text-[10px] font-mono text-text-faint font-normal">
                    ({(step.elapsedMs / 1000).toFixed(1)}s)
                  </span>
                )}
              </div>
              {step.detail && (
                <span className="text-[11px] font-mono text-text-muted max-w-sm sm:max-w-md italic truncate">
                  {step.detail}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ==========================================
// PERSISTENCE INDICATOR (WARNING CHIP)
// ==========================================
interface PersistenceIndicatorProps {
  ok: boolean;
  operationId?: string;
}

export const PersistenceIndicator: React.FC<PersistenceIndicatorProps> = ({
  ok,
  operationId
}) => {
  if (ok) return null;

  return (
    <div className="inline-flex items-center gap-1.5 bg-[rgba(242,181,68,0.1)] hover:bg-opacity-80 border border-orange-500/20 text-orange-400 text-xs font-mono font-medium px-2 py-1 rounded-sm select-none cursor-help group relative my-1">
      <AlertTriangle className="w-3.5 h-3.5" />
      <span>Result shown but not saved</span>
      
      {operationId && (
        <div className="absolute bottom-full mb-1 border border-border-dim bg-surface p-2 text-[10px] text-text-muted rounded shadow-md hidden group-hover:block whitespace-nowrap z-50">
          Operation ID: <span className="font-mono text-white select-all">{operationId}</span>
        </div>
      )}
    </div>
  );
};
