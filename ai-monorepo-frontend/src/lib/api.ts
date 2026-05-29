/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { 
  SSEDataEvent, 
  SSEProgressEvent, 
  SSEDoneEvent, 
  SSEErrorEvent, 
  HistoryRecord, 
  ProjectId 
} from '../types';

// Helper to retrieve URLs safely
export function getServiceUrl(name: string): string {
  // Support NEXT_PUBLIC_* prefixes in Vite
  const metaEnv = (import.meta as any).env || {};
  const viteNextPublic = metaEnv[`VITE_NEXT_PUBLIC_${name}`];
  const nextPublic = metaEnv[`NEXT_PUBLIC_${name}`];
  const directEnv = metaEnv[name];
  
  const value = viteNextPublic || nextPublic || directEnv || '';
  return value.trim();
}

export const SERVICE_URLS = {
  playground: getServiceUrl('PLAYGROUND_URL'),
  support: getServiceUrl('SUPPORT_URL'),
  webagent: getServiceUrl('WEBAGENT_URL'),
  deepresearch: getServiceUrl('DEEPRESEARCH_URL'),
  image: getServiceUrl('IMAGE_URL'),
  capstone: getServiceUrl('CAPSTONE_URL'),
};

interface StreamHandlers {
  onData?: (data: SSEDataEvent) => void;
  onProgress?: (progress: SSEProgressEvent) => void;
  onDone?: (done: SSEDoneEvent) => void;
  onError?: (error: SSEErrorEvent) => void;
}

/**
 * Perform manual post-based SSE stream consumption as per streaming contract.
 */
export async function fetchSSEStream(
  url: string,
  bodyObj: any,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const controller = new AbortController();
  
  // Link outer signal if provided
  if (signal) {
    signal.addEventListener('abort', () => controller.abort());
  }

  // 60-second timeout
  const timeoutId = setTimeout(() => {
    controller.abort();
    if (handlers.onError) {
      handlers.onError({
        action: 'connection_timeout',
        reason: 'Request timed out after 60 seconds.'
      });
    }
  }, 60000);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify(bodyObj),
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errText = await response.text().catch(() => 'Unknown network error');
      throw new Error(`Server returned status ${response.status}: ${errText}`);
    }

    if (!response.body) {
      throw new Error('Response body is null or not readable.');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split chunks on double newlines
      const blocks = buffer.split(/\n\n|\r\n\r\n/);
      
      // Save the last element (which might be an incomplete frame) back to the buffer
      buffer = blocks.pop() || '';

      for (const block of blocks) {
        if (!block.trim()) continue;

        let currentEvent = 'data';
        let currentDataStr = '';

        const lines = block.split(/\n|\r/);
        for (const line of lines) {
          const colonIdx = line.indexOf(':');
          if (colonIdx === -1) continue;

          const key = line.slice(0, colonIdx).trim();
          const val = line.slice(colonIdx + 1).trim();

          if (key === 'event') {
            currentEvent = val;
          } else if (key === 'data') {
            currentDataStr = val; // handle multiple chunks or single data
          }
        }

        if (currentDataStr) {
          try {
            const dataObj = JSON.parse(currentDataStr);
            
            switch (currentEvent) {
              case 'data':
                if (handlers.onData) handlers.onData(dataObj as SSEDataEvent);
                break;
              case 'progress':
                if (handlers.onProgress) handlers.onProgress(dataObj as SSEProgressEvent);
                break;
              case 'done':
                if (handlers.onDone) handlers.onDone(dataObj as SSEDoneEvent);
                break;
              case 'error':
                if (handlers.onError) handlers.onError(dataObj as SSEErrorEvent);
                break;
              default:
                // Handle as "data" fallback if event is not specified
                if (handlers.onData && dataObj.text !== undefined) {
                  handlers.onData(dataObj as SSEDataEvent);
                }
                break;
            }
          } catch (e) {
            console.warn('Failed to parse SSE JSON data:', currentDataStr, e);
          }
        }
      }
    }
  } catch (error: any) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      // Already handled in timeout or user manually aborted, don't double trigger unless timeout
      return;
    }
    if (handlers.onError) {
      handlers.onError({
        action: 'network_request',
        reason: error.message || 'Streaming collection failed'
      });
    }
  }
}

// Global variable config warnings
export function getEnvWarningMsg(): string | null {
  const missing = Object.entries(SERVICE_URLS)
    .filter(([_, url]) => !url)
    .map(([key]) => `NEXT_PUBLIC_${key.toUpperCase()}_URL`);
  
  if (missing.length > 0) {
    return `The following environment variables are not configured: ${missing.join(', ')}. The applet operates in client-side persistence mode for demonstration.`;
  }
  return null;
}

// Single-Source local storage fallback for histories to maintain rich client experience 
const STORAGE_PREFIX = 'ai_practice_monorepo_history_';

export function getLocalHistory(projectId: ProjectId): HistoryRecord[] {
  try {
    const data = localStorage.getItem(`${STORAGE_PREFIX}${projectId}`);
    return data ? JSON.parse(data) : [];
  } catch (e) {
    console.error('Local history load error:', e);
    return [];
  }
}

export function saveLocalHistoryItem(projectId: ProjectId, record: HistoryRecord): void {
  try {
    const list = getLocalHistory(projectId);
    // Avoid double entries
    const filtered = list.filter(item => item.id !== record.id);
    filtered.unshift(record); // newest first
    localStorage.setItem(`${STORAGE_PREFIX}${projectId}`, JSON.stringify(filtered));
  } catch (e) {
    console.error('Local history save error:', e);
  }
}

export function deleteLocalHistoryItem(projectId: ProjectId, id: string): void {
  try {
    const list = getLocalHistory(projectId);
    const filtered = list.filter(item => item.id !== id);
    localStorage.setItem(`${STORAGE_PREFIX}${projectId}`, JSON.stringify(filtered));
  } catch (e) {
    console.error('Local history delete error:', e);
  }
}

// CLIENT API UTILITIES (FALLS BACK SILENTLY IF URLS ARE UNSET)
export async function getRemoteHistory(projectId: ProjectId): Promise<HistoryRecord[]> {
  const baseUrl = SERVICE_URLS[projectId];
  if (!baseUrl) {
    // If env URL is not set, we use our mock local storage data directly 
    return getLocalHistory(projectId);
  }

  try {
    const res = await fetch(`${baseUrl}/history`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });
    
    if (!res.ok) {
      throw new Error(`Failed to load history (${res.status})`);
    }
    
    return await res.json();
  } catch (err: any) {
    console.warn(`Fetch history failed for ${projectId}, using local storage:`, err);
    return getLocalHistory(projectId);
  }
}

export async function getRemoteHistoryDetail(projectId: ProjectId, id: string): Promise<HistoryRecord> {
  const baseUrl = SERVICE_URLS[projectId];
  if (!baseUrl) {
    const local = getLocalHistory(projectId).find(item => item.id === id);
    if (!local) throw new Error(`History id ${id} not found locally.`);
    return local;
  }

  try {
    const res = await fetch(`${baseUrl}/history/${id}`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });
    
    if (!res.ok) {
      if (res.status === 404) throw new Error('History record not found');
      throw new Error(`Backend fetch error (status: ${res.status})`);
    }
    
    return await res.json();
  } catch (err: any) {
    console.warn(`Fetch history detail failed for ${projectId}, fallback to local:`, err);
    const local = getLocalHistory(projectId).find(item => item.id === id);
    if (!local) throw new Error(`History id ${id} not found in fallback cache either: ${err.message}`);
    return local;
  }
}

// IMAGE SPECIFIC ENDPOINTS
export async function generateImage(prompt: string, model?: string): Promise<{ mime_type: string; data_base64: string; persistence?: { ok: boolean; operation_id?: string } }> {
  const baseUrl = SERVICE_URLS.image;
  if (!baseUrl) {
    // Return a beautiful mock image or simulate if service not set up
    await new Promise(resolve => setTimeout(resolve, 1500));
    // Provide a simple placeholder canvas rendering so the application is full-featured and non-empty
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 512;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.fillStyle = '#1A1E25';
      ctx.fillRect(0, 0, 512, 512);
      ctx.fillStyle = '#6D8BFF';
      ctx.font = 'bold 20px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(prompt.slice(0, 30) + (prompt.length > 30 ? '...' : ''), 256, 230);
      ctx.fillStyle = '#9AA4B2';
      ctx.font = '14px JetBrains Mono, monospace';
      ctx.fillText(model || 'Default Generator', 256, 270);
    }
    const dataUrl = canvas.toDataURL('image/png');
    const base64 = dataUrl.split(',')[1];
    return {
      mime_type: 'image/png',
      data_base64: base64,
      persistence: { ok: false, operation_id: 'local_persistence_active' }
    };
  }

  const res = await fetch(`${baseUrl}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, model })
  });

  if (!res.ok) {
    const text = await res.text().catch(() => 'Status error');
    throw new Error(`Image Service error: ${text}`);
  }

  return await res.json();
}

export async function getImageModels(): Promise<string[]> {
  const baseUrl = SERVICE_URLS.image;
  if (!baseUrl) {
    return ['stable-diffusion-xl', 'imagen-3-generate', 'flux-schnell'];
  }
  try {
    const res = await fetch(`${baseUrl}/models`);
    if (!res.ok) throw new Error('Failed to load image models');
    return await res.json();
  } catch (err) {
    console.warn('Failed to retrieve image models, using standard presets.', err);
    return ['stable-diffusion-xl', 'imagen-3-generate', 'flux-schnell'];
  }
}

// CAPSTONE MULTIPART FILE UPLOAD
export async function uploadCapstoneDocuments(files: File[]): Promise<Array<{ filename: string; size: number }>> {
  const baseUrl = SERVICE_URLS.capstone;
  if (!baseUrl) {
    // Local simulation of document upload persistence
    await new Promise(resolve => setTimeout(resolve, 1000));
    return files.map(f => ({ filename: f.name, size: f.size }));
  }

  const formData = new FormData();
  files.forEach(f => formData.append('documents', f));

  const res = await fetch(`${baseUrl}/documents`, {
    method: 'POST',
    body: formData
  });

  if (!res.ok) {
    const text = await res.text().catch(() => 'Upload failure');
    throw new Error(`File Ingestion Error: ${text}`);
  }

  return await res.json();
}

// CHATBOT SESSIONS (FOR SUPPORT CHAT ROUTINE)
export async function createChatSession(): Promise<{ session_id: string }> {
  const baseUrl = SERVICE_URLS.support;
  if (!baseUrl) {
    return { session_id: `session_local_${Math.random().toString(36).slice(2, 11)}` };
  }
  
  const res = await fetch(`${baseUrl}/session`, { method: 'POST' });
  if (!res.ok) throw new Error('Could not establish a chatbot session.');
  return await res.json();
}

export async function deleteChatSession(id: string): Promise<void> {
  const baseUrl = SERVICE_URLS.support;
  if (!baseUrl) return;
  await fetch(`${baseUrl}/session/${id}`, { method: 'DELETE' });
}
