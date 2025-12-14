/**
 * Chat Interface Component - Example implementation
 * 
 * This component demonstrates how to use the useAsyncMessage hook
 * for async message generation with WebSocket streaming.
 */

import React, { useState, useRef, useEffect } from 'react';
import { useAsyncMessage } from '@/hooks/useAsyncMessage';
import '../styles/ChatInterface.css';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: string[];
  citations?: Record<string, any>;
  status?: 'pending' | 'streaming' | 'complete' | 'error';
}

interface ChatInterfaceProps {
  conversationId: string;
  workspaceId: string;
  initialMessages?: Message[];
}

export function ChatInterface({
  conversationId,
  workspaceId,
  initialMessages = [],
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [query, setQuery] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const {
    sendMessage,
    cancel,
    status,
    content,
    error,
    isLoading,
    isGenerating,
  } = useAsyncMessage({
    conversationId,
    workspaceId,
    useWebSocket: true,
    pollInterval: 500,
  });

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, content]);

  // Update streaming message in real-time
  useEffect(() => {
    if (status === 'streaming' || status === 'pending') {
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg?.role === 'assistant' && lastMsg?.status !== 'complete') {
          return [
            ...prev.slice(0, -1),
            {
              ...lastMsg,
              content,
              status: status as 'pending' | 'streaming',
            },
          ];
        }
        return prev;
      });
    } else if (status === 'complete') {
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg?.role === 'assistant') {
          return [
            ...prev.slice(0, -1),
            {
              ...lastMsg,
              content,
              status: 'complete',
            },
          ];
        }
        return prev;
      });
    }
  }, [status, content]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!query.trim()) return;

    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: query,
      status: 'complete',
    };
    setMessages((prev) => [...prev, userMessage]);

    // Add placeholder for assistant message
    const assistantMessage: Message = {
      id: `${Date.now()}-assistant`,
      role: 'assistant',
      content: '',
      status: 'pending',
    };
    setMessages((prev) => [...prev, assistantMessage]);

    // Clear input
    setQuery('');

    // Send to backend
    await sendMessage(query);
  };

  return (
    <div className="chat-interface">
      <div className="messages-container">
        {messages.map((msg) => (
          <div key={msg.id} className={`message message-${msg.role}`}>
            <div className="message-header">
              <span className="role">{msg.role === 'user' ? 'You' : 'Assistant'}</span>
              {msg.status && msg.status !== 'complete' && (
                <span className={`status status-${msg.status}`}>
                  {msg.status === 'pending' && '⏳'}
                  {msg.status === 'streaming' && '✍️'}
                  {msg.status === 'error' && '❌'}
                  {msg.status}
                </span>
              )}
            </div>

            <div className="message-content">
              {msg.content || (
                <span className="placeholder">Generating response...</span>
              )}
            </div>

            {msg.sources && msg.sources.length > 0 && (
              <div className="message-sources">
                <strong>Sources:</strong>
                <ul>
                  {msg.sources.map((source, idx) => (
                    <li key={idx}>{source}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}

        {error && (
          <div className="error-message">
            <strong>Error:</strong> {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form className="input-form" onSubmit={handleSendMessage}>
        <div className="input-wrapper">
          <input
            type="text"
            placeholder={
              isGenerating
                ? 'Waiting for response...'
                : 'Ask a question about your documents...'
            }
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={isLoading || isGenerating}
            className="message-input"
          />
          <button
            type="submit"
            disabled={isLoading || isGenerating || !query.trim()}
            className="send-button"
          >
            {isLoading ? '⏳' : '📤'}
          </button>

          {isGenerating && (
            <button
              type="button"
              onClick={cancel}
              className="cancel-button"
            >
              Cancel
            </button>
          )}
        </div>

        {isGenerating && (
          <div className="generation-indicator">
            <div className="spinner" />
            <span>
              {status === 'pending' ? 'Queued...' : 'Generating response...'}
            </span>
          </div>
        )}
      </form>
    </div>
  );
}

/**
 * Example usage:
 * 
 * function App() {
 *   return (
 *     <ChatInterface
 *       conversationId="12345"
 *       workspaceId="67890"
 *     />
 *   );
 * }
 */
