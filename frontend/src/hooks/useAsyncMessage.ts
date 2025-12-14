/**
 * React hook for async message generation with WebSocket streaming
 *
 * Usage:
 * const { sendMessage, message, status, content, error } = useAsyncMessage();
 *
 * sendMessage("What is quantum computing?");
 *
 * if (status === 'streaming') return <div>Generating...</div>;
 * return <div>{content}</div>;
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import axios from 'axios';

interface MessageData {
  messageId: string;
  status: 'pending' | 'streaming' | 'complete' | 'error';
  content: string;
  sources: string[];
  citations: Record<string, any>;
  tokensUsed?: number;
  generationTime?: number;
  modelUsed?: string;
  errorMessage?: string;
}

interface UseAsyncMessageOptions {
  conversationId: string;
  workspaceId: string;
  apiUrl?: string;
  useWebSocket?: boolean;
  pollInterval?: number;
}

export function useAsyncMessage({
  conversationId,
  workspaceId,
  apiUrl = '/api',
  useWebSocket = true,
  pollInterval = 500,
}: UseAsyncMessageOptions) {
  const [message, setMessage] = useState<MessageData | null>(null);
  const [status, setStatus] = useState<'idle' | 'pending' | 'streaming' | 'complete' | 'error'>('idle');
  const [content, setContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup WebSocket and polling on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  /**
   * Connect to WebSocket for real-time streaming
   */
  const connectWebSocket = useCallback((messageId: string) => {
    try {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/messages/${messageId}/stream?conversation_id=${conversationId}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log(`[WebSocket] Connected to message stream: ${messageId}`);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          switch (data.type) {
            case 'status':
              setStatus(data.status);
              break;

            case 'token':
              setContent((prev) => prev + data.token);
              setStatus('streaming');
              break;

            case 'complete':
              setContent(data.content);
              setStatus('complete');
              setMessage({
                messageId,
                status: 'complete',
                content: data.content,
                sources: data.sources || [],
                citations: data.citations || {},
                tokensUsed: data.tokens_used,
                generationTime: data.generation_time,
                modelUsed: data.model_used,
              });
              // Close after a short delay
              setTimeout(() => ws.close(), 500);
              break;

            case 'error':
              setStatus('error');
              setError(data.error || 'Unknown error occurred');
              break;

            case 'close':
              ws.close();
              break;
          }
        } catch (err) {
          console.error('[WebSocket] Error parsing message:', err);
        }
      };

      ws.onerror = (event) => {
        console.error('[WebSocket] Error:', event);
        setStatus('error');
        setError('WebSocket connection error');
      };

      ws.onclose = () => {
        console.log('[WebSocket] Disconnected');
        wsRef.current = null;
      };
    } catch (err) {
      console.error('[WebSocket] Failed to connect:', err);
      setStatus('error');
      setError('Failed to connect to WebSocket');
    }
  }, [conversationId]);

  /**
   * Poll for message status (fallback if WebSocket unavailable)
   */
  const startPolling = useCallback((messageId: string) => {
    // Stop any existing polling
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }

    pollIntervalRef.current = setInterval(async () => {
      try {
        const response = await axios.get(
          `${apiUrl}/conversations/${conversationId}/messages/${messageId}/status`
        );
        const data = response.data;

        setStatus(data.status);
        setContent(data.content || '');

        if (data.status === 'complete' || data.status === 'error') {
          clearInterval(pollIntervalRef.current!);
          pollIntervalRef.current = null;

          setMessage({
            messageId,
            status: data.status,
            content: data.content,
            sources: data.sources || [],
            citations: data.citations || {},
            tokensUsed: data.tokens_used,
            generationTime: data.generation_time,
            modelUsed: data.model_used,
            errorMessage: data.error_message,
          });

          if (data.status === 'error') {
            setError(data.error_message || 'Generation failed');
          }
        }
      } catch (err) {
        console.error('[Polling] Error checking status:', err);
        setError('Failed to check message status');
      }
    }, pollInterval);
  }, [conversationId, apiUrl, pollInterval]);

  /**
   * Send message and start generation
   */
  const sendMessage = useCallback(
    async (query: string, options?: Partial<Record<string, any>>) => {
      try {
        setIsLoading(true);
        setError(null);
        setContent('');
        setStatus('pending');

        const response = await axios.post(
          `${apiUrl}/conversations/${conversationId}/messages`,
          {
            query,
            workspace_id: workspaceId,
            prompt_type: options?.promptType || 'qa',
            temperature: options?.temperature || 0.3,
            provider: options?.provider || 'ollama',
            model: options?.model,
            max_context_tokens: options?.maxContextTokens || 4000,
            top_k: options?.topK || 20,
            llm_max_tokens: options?.llmMaxTokens || 1500,
            verify_citations: options?.verifyCitations ?? true,
          }
        );

        const { message_id } = response.data;
        setMessage(prev => ({
          ...prev,
          messageId: message_id,
        } as MessageData));

        // Connect WebSocket or start polling
        if (useWebSocket) {
          connectWebSocket(message_id);
        } else {
          startPolling(message_id);
        }

        setIsLoading(false);
      } catch (err: any) {
        console.error('[useAsyncMessage] Error sending message:', err);
        setError(err.response?.data?.detail || err.message || 'Failed to send message');
        setStatus('error');
        setIsLoading(false);
      }
    },
    [conversationId, workspaceId, apiUrl, useWebSocket, connectWebSocket, startPolling]
  );

  /**
   * Cancel ongoing message generation
   */
  const cancel = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    setStatus('idle');
    setContent('');
    setError(null);
    setMessage(null);
  }, []);

  return {
    sendMessage,
    cancel,
    message,
    status,
    content,
    error,
    isLoading,
    isGenerating: status === 'pending' || status === 'streaming',
  };
}
