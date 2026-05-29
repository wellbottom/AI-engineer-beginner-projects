/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

// Project identifiers
export type ProjectId = 'playground' | 'support' | 'web-agent' | 'deep-research' | 'image' | 'capstone';

// Project Info for Dashboard
export interface ProjectInfo {
  id: ProjectId;
  name: string;
  description: string;
  providers: string[];
  icon: string;
  path: string;
}

// SSE stream event types
export interface SSEDataEvent {
  text: string;
}

export interface SSEProgressEvent {
  phase: string;
  step: number;
  detail?: string;
}

export interface SSEDoneEvent {
  usage?: {
    prompt_tokens: number;
    output_tokens: number;
    total_tokens: number;
  };
  citations?: Array<{
    url: string;
    title: string;
  }>;
  report?: {
    title: string;
    introduction: string;
    sections: Array<{
      sub_question: string;
      body: string;
      citations: Array<{ url: string; title: string }>;
    }>;
    conclusion: string;
  };
  answer?: string;
  tools_invoked?: Array<{
    tool: string;
    ok: boolean;
    error?: string;
  }>;
  sources?: string[];
  step_limit_reached?: boolean;
  persistence?: {
    ok: boolean;
    operation_id?: string;
  };
  [key: string]: any; // Allow other done metadata
}

export interface SSEErrorEvent {
  action: string;
  reason: string;
}

// Client Input Validation Configuration
export interface PlaygroundInputs {
  prompt: string;
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
  model?: string;
}

export interface SupportInputs {
  session_id: string;
  message: string;
}

export interface WebAgentInputs {
  question: string;
}

export interface DeepResearchInputs {
  topic: string;
}

export interface ImageInputs {
  prompt: string;
  model?: string;
}

export interface CapstoneInputs {
  task: string;
  documents?: File[]; // Multi-part upload handles files separate or referenced
}

// State Matrix types
export type RequestState = 
  | 'idle' 
  | 'submitting' 
  | 'streaming' 
  | 'success' 
  | 'empty-result' 
  | 'validation-error' 
  | 'error' 
  | 'persistence-failure';

// History type structures
export interface HistoryRecord {
  id: string;
  projectId: ProjectId;
  created_at: string; // ISO string
  label: string; // Brief prompt preview, topic, task or message
  inputs: any;  // Project-specific inputs
  outputs: {
    text?: string;
    progress?: SSEProgressEvent[];
    metadata?: SSEDoneEvent;
    imageUrl?: string; // specifically for image project
    error?: { action: string; reason: string };
  };
}
