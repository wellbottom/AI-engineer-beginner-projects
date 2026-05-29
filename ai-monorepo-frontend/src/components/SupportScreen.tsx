/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useRef } from 'react';
import { Send, User, Cpu, AlertTriangle, MessageSquare, RefreshCw } from 'lucide-react';
import { 
  Card, 
  Button, 
  Textarea, 
  StreamingMarkdown, 
  ErrorBanner, 
  Badge, 
  PersistenceIndicator 
} from './SharedComponents';
import { 
  fetchSSEStream, 
  SERVICE_URLS, 
  saveLocalHistoryItem, 
  createChatSession, 
  deleteChatSession 
} from '../lib/api';
import { HistoryRecord, SSEDataEvent, SSEDoneEvent, SSEErrorEvent } from '../types';

interface Message {
  id: string;
  sender: 'user' | 'assistant' | 'system';
  text: string;
  isStreaming?: boolean;
}

interface SupportScreenProps {
  onAddHistory: (record: HistoryRecord) => void;
}

export const SupportScreen: React.FC<SupportScreenProps> = ({ onAddHistory }) => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      sender: 'system',
      text: 'Session established. State synced on gateway.',
    }
  ]);
  const [composer, setComposer] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(true);

  // Errors state
  const [validationError, setValidationError] = useState('');
  const [chatbotError, setChatbotError] = useState<SSEErrorEvent | null>(null);
  const [persistenceMeta, setPersistenceMeta] = useState<any>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Initialize chatbot session
  useEffect(() => {
    let active = true;
    const initializeSession = async () => {
      try {
        setSessionLoading(true);
        const { session_id } = await createChatSession();
        if (active) {
          setSessionId(session_id);
          setMessages(prev => [
            ...prev,
            {
              id: 'agent-greeting',
              sender: 'assistant',
              text: 'Hello! I am your AI Support Companion. How can I assist with your services, queries, or sandbox items today?'
            }
          ]);
        }
      } catch (err) {
        console.warn('Backend session creator failed. Using client simulation session.', err);
        if (active) {
          setSessionId(`local_${Math.random().toString(36).substring(2, 9)}`);
          setMessages(prev => [
            ...prev,
            {
              id: 'agent-greeting',
              sender: 'assistant',
              text: 'Support Gateway running in local emulation. How can I assist with the monorepo operations?'
            }
          ]);
        }
      } finally {
        if (active) setSessionLoading(false);
      }
    };

    initializeSession();

    return () => {
      active = false;
      if (sessionId && !sessionId.startsWith('local_')) {
        deleteChatSession(sessionId).catch(console.error);
      }
    };
  }, []);

  // Scroll to bottom when messages append
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isStreaming]);

  const handleSend = async () => {
    if (loading || isStreaming || sessionLoading) return;

    const trimmed = composer.trim();
    if (!trimmed) {
      setValidationError('Message cannot be empty.');
      return;
    }
    if (trimmed.length > 4000) {
      setValidationError(`Message is over the 4000 limit (${trimmed.length} characters).`);
      return;
    }

    setValidationError('');
    setComposer('');
    setChatbotError(null);
    setPersistenceMeta(null);

    const userMsgId = `usr_${Date.now()}`;
    const assistantMsgId = `asst_${Date.now()}`;

    // Append user message
    setMessages(prev => [
      ...prev,
      { id: userMsgId, sender: 'user', text: trimmed }
    ]);

    setLoading(true);

    const targetUrl = SERVICE_URLS.support ? `${SERVICE_URLS.support}/chat` : '';
    
    let completeText = '';
    let finalMeta: SSEDoneEvent | null = null;
    let sError: SSEErrorEvent | null = null;

    if (!targetUrl) {
      // Direct emulation mode
      try {
        await new Promise(resolve => setTimeout(resolve, 800));
        setLoading(false);
        setIsStreaming(true);

        const lower = trimmed.toLowerCase();
        let replyString = "";
        
        if (lower.includes('price') || lower.includes('billing') || lower.includes('cost')) {
          replyString = "I detected queries around billing. This repository operates strictly in a local sandbox mode; no charge will occur for utilizing simulation runs. Make sure you customize model thresholds inside parameters.";
        } else if (lower.includes('unsupported') || lower.includes('outside') || lower.includes('weather') || lower.includes('sports')) {
          replyString = "outside_supported_topics: Weather forecasts, sports matches, and third-party stock telemetry fall outside supported support scopes. Please consult specialized API endpoints.";
        } else {
          replyString = `Your message regarding "${trimmed.slice(0, 40)}" has been parsed. In support environment chat models:
1. Message inputs are length-tested statically.
2. Context keys and states persist cleanly in session ID \`${sessionId}\`.
3. Safe markdown formatting can be utilized dynamically.`;
        }

        // Output as dynamic response
        setMessages(prev => [
          ...prev,
          { id: assistantMsgId, sender: 'assistant', text: '', isStreaming: true }
        ]);

        const words = replyString.split(' ');
        for (let i = 0; i < words.length; i++) {
          await new Promise(resolve => setTimeout(resolve, 40));
          const chunk = words[i] + ' ';
          completeText += chunk;
          
          setMessages(prev => prev.map(msg => 
            msg.id === assistantMsgId ? { ...msg, text: completeText } : msg
          ));
        }

        finalMeta = {
          persistence: { ok: false, operation_id: 'emulated_support' }
        };
        setPersistenceMeta(finalMeta.persistence);
      } catch (err: any) {
        setChatbotError({
          action: 'emulated_chat',
          reason: err.message || 'Stream generation crashed'
        });
      } finally {
        setIsStreaming(false);
        setMessages(prev => prev.map(msg => 
          msg.id === assistantMsgId ? { ...msg, isStreaming: false } : msg
        ));
      }
    } else {
      // Connect to streamed endpoint
      setMessages(prev => [
        ...prev,
        { id: assistantMsgId, sender: 'assistant', text: '', isStreaming: true }
      ]);
      setIsStreaming(true);

      await fetchSSEStream(
        targetUrl,
        {
          session_id: sessionId,
          message: trimmed
        },
        {
          onData: (eventData: SSEDataEvent) => {
            setLoading(false);
            completeText += eventData.text;
            setMessages(prev => prev.map(msg => 
              msg.id === assistantMsgId ? { ...msg, text: completeText } : msg
            ));
          },
          onDone: (done: SSEDoneEvent) => {
            finalMeta = done;
            setPersistenceMeta(done.persistence || null);
          },
          onError: (err: SSEErrorEvent) => {
            sError = err;
            setChatbotError(err);
          }
        }
      );

      setIsStreaming(false);
      setLoading(false);
      setMessages(prev => prev.map(msg => 
        msg.id === assistantMsgId ? { ...msg, isStreaming: false } : msg
      ));
    }

    // Save success or failed to local history log as per State Matrix
    const histRecord: HistoryRecord = {
      id: `chat_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      projectId: 'support',
      created_at: new Date().toISOString(),
      label: trimmed.length > 50 ? `${trimmed.substring(0, 50)}...` : trimmed,
      inputs: {
        session_id: sessionId,
        message: trimmed
      },
      outputs: {
        text: completeText || undefined,
        metadata: finalMeta || undefined,
        error: sError || undefined
      }
    };

    saveLocalHistoryItem('support', histRecord);
    onAddHistory(histRecord);
  };

  const handleResetSession = async () => {
    setSessionLoading(true);
    setComposer('');
    setValidationError('');
    setChatbotError(null);
    setPersistenceMeta(null);
    
    // Attempt deleting previous session if not local
    if (sessionId && !sessionId.startsWith('local_')) {
      await deleteChatSession(sessionId).catch(console.error);
    }

    try {
      const { session_id } = await createChatSession();
      setSessionId(session_id);
      setMessages([
        { id: `sys_${Date.now()}`, sender: 'system', text: 'New server connection established. Previous state deleted.' },
        { id: `asst_greet_${Date.now()}`, sender: 'assistant', text: 'Hello! This is a fresh support session. What can I answer for you?' }
      ]);
    } catch {
      setSessionId(`local_${Math.random().toString(36).substring(2, 9)}`);
      setMessages([
        { id: `sys_${Date.now()}`, sender: 'system', text: 'Fresh local backup session established.' },
        { id: `asst_greet_${Date.now()}`, sender: 'assistant', text: 'Emulated support is ready for your search queries.' }
      ]);
    } finally {
      setSessionLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="max-w-3xl mx-auto w-full flex flex-col gap-6">
      
      {/* Session info bar */}
      <div className="flex items-center justify-between border border-border-dim bg-surface p-3 rounded-lg select-none text-xs font-mono">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-text-muted" />
          <span className="text-text-faint">Session ID:</span>
          {sessionLoading ? (
            <span className="text-text-muted animate-pulse">Allocating...</span>
          ) : (
            <span className="text-white font-medium select-all truncate max-w-[140px] sm:max-w-[200px]">{sessionId}</span>
          )}
        </div>

        <Button
          variant="ghost"
          onClick={handleResetSession}
          disabled={sessionLoading || loading || isStreaming}
          className="h-7 px-2.5 ml-2 border border-border-dim hover:border-border-strong text-[11px] gap-1.5"
        >
          <RefreshCw className="w-3 h-3" />
          <span>Reset Session</span>
        </Button>
      </div>

      {/* Messages Thread pane */}
      <div className="bg-surface border border-border-dim rounded-lg p-5 flex flex-col gap-5 min-h-[380px] max-h-[500px] overflow-y-auto shadow-sm select-text">
        {messages.map((msg) => {
          if (msg.sender === 'system') {
            return (
              <div key={msg.id} className="self-center bg-surface-2 border border-border-dim text-[11px] font-mono select-none px-3 py-1 rounded text-text-faint tracking-wider my-1">
                {msg.text}
              </div>
            );
          }

          const isUser = msg.sender === 'user';
          // Check for out of topic prefix
          const isOutOfTopic = msg.text.startsWith('outside_supported_topics:');
          const cleanText = isOutOfTopic ? msg.text.replace('outside_supported_topics:', '').trim() : msg.text;

          return (
            <div
              key={msg.id}
              className={`flex flex-col gap-1.5 max-w-[85%] ${isUser ? 'self-end items-end' : 'self-start items-start'}`}
            >
              {/* Header profile label */}
              <div className="flex items-center gap-1 text-[10px] font-mono text-text-faint select-none">
                {isUser ? (
                  <>
                    <span>You</span>
                    <User className="w-3 h-3 text-text-faint" />
                  </>
                ) : (
                  <>
                    <Cpu className="w-3 h-3 text-primary-main" />
                    <span className="text-primary-main font-semibold">Assistant</span>
                  </>
                )}
              </div>

              {/* Message box */}
              <div
                className={`px-4 py-2.5 rounded-lg text-sm border font-sans ${isUser ? 'bg-surface-3 text-text-main rounded-tr-none border-border-dim' : 'bg-surface py-3 text-text-main rounded-tl-none border-border-dim'}`}
              >
                {isOutOfTopic && (
                  <div className="mb-2 select-none">
                    <Badge variant="neutral">outside supported topics</Badge>
                  </div>
                )}
                
                {isUser ? (
                  <p className="whitespace-pre-wrap leading-relaxed break-words">{cleanText}</p>
                ) : (
                  <StreamingMarkdown content={cleanText} isStreaming={msg.isStreaming} />
                )}
              </div>
            </div>
          );
        })}
        <div ref={scrollRef} />
      </div>

      {/* Persistence indicator warning */}
      {persistenceMeta && !persistenceMeta.ok && (
        <div className="self-start select-none">
          <PersistenceIndicator
            ok={persistenceMeta.ok}
            operationId={persistenceMeta.operation_id}
          />
        </div>
      )}

      {/* Gateway Failure Error Banner (States 5.6) */}
      {chatbotError && (
        <ErrorBanner
          action="assistant_connection"
          reason="Assistant temporarily unavailable. Session parameters and transcript histories have been retained."
        />
      )}

      {/* Growing Composer text bar */}
      <div className="bg-surface border border-border-dim rounded-lg p-3 sm:p-4 shadow-md">
        <div className="flex flex-col gap-3 relative">
          <Textarea
            id="chat-textarea-compose"
            placeholder={sessionLoading ? "Awaiting session initialization..." : "Describe your custom issue (Enter sends, Shift+Enter line-break)..."}
            value={composer}
            onChange={(e) => setComposer(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={sessionLoading || loading || isStreaming}
            maxLength={4000}
            error={validationError}
            className="min-h-[64px]"
          />
          
          <div className="flex items-center justify-between border-t border-border-dim pt-2 mt-1">
            <span className="text-[10px] font-mono text-text-faint select-none">
              Supports markdown.
            </span>
            
            <Button
              variant="primary"
              onClick={handleSend}
              disabled={sessionLoading || loading || isStreaming || !composer.trim()}
              isLoading={loading || isStreaming}
              className="px-5 text-xs font-semibold h-9 shrink-0 gap-1.5"
            >
              <span>Send Message</span>
              <Send className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </div>

    </div>
  );
};
