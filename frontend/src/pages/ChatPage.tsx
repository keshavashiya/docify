import { useState, useEffect, useRef } from 'react';
import { useAppStore } from '../stores/appStore';
import { conversationsApi } from '../services/api';
import type { Conversation, Message, GeneratedMessageResponse, GenerationMetrics } from '../types';

interface WebSocketMessageData {
  type: 'status' | 'token' | 'complete' | 'error' | 'close';
  status?: string;
  content?: string;
  token?: string;
  error?: string;
  sources?: string[];
  citations?: Record<string, any>;
  tokens_used?: number;
  generation_time?: number;
  model_used?: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  sources?: string[];
  metrics?: GenerationMetrics;
  verificationScore?: number;
  isLoading?: boolean;
}

export default function ChatPage() {
  const { currentWorkspace, currentConversation, setCurrentConversation } = useAppStore();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showConversations, setShowConversations] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (currentWorkspace) {
      loadConversations();
    }
  }, [currentWorkspace]);

  useEffect(() => {
    if (currentConversation) {
      loadMessages(currentConversation.id);
    } else {
      setMessages([]);
    }
  }, [currentConversation]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadConversations = async () => {
    if (!currentWorkspace) return;
    try {
      const data = await conversationsApi.list(currentWorkspace.id);
      setConversations(data);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadMessages = async (conversationId: string) => {
    try {
      const data = await conversationsApi.getMessages(conversationId);
      setMessages(data.map(m => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
        sources: m.sources,
      })));
    } catch (error) {
      console.error('Failed to load messages:', error);
    }
  };

  const createNewConversation = async () => {
    if (!currentWorkspace) return;
    try {
      const conversation = await conversationsApi.create({
        workspace_id: currentWorkspace.id,
        title: 'New Chat',
      });
      setConversations(prev => [conversation, ...prev]);
      setCurrentConversation(conversation);
      setMessages([]);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const connectWebSocket = (messageId: string, conversationId: string, loadingId: string) => {
    try {
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const protocol = apiUrl.startsWith('https') ? 'wss:' : 'ws:';
      const host = apiUrl.replace('https://', '').replace('http://', '');
      const wsUrl = `${protocol}//${host}/ws/messages/${messageId}/stream?conversation_id=${conversationId}`;
      
      console.log('[WebSocket] Connecting to:', wsUrl);
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[WebSocket] Connected for message:', messageId);
      };

      ws.onmessage = (event) => {
        try {
          const data: WebSocketMessageData = JSON.parse(event.data);
          console.log('[WebSocket] Received:', data.type, data);

          switch (data.type) {
            case 'status':
              setMessages(prev => prev.map(m =>
                m.id === loadingId ? {
                  ...m,
                  id: messageId,
                  isLoading: true,
                } : m
              ));
              break;

            case 'token':
              setMessages(prev => prev.map(m =>
                m.id === loadingId || m.id === messageId ? {
                  ...m,
                  id: messageId,
                  content: (m.content || '') + (data.token || ''),
                  isLoading: true,
                } : m
              ));
              break;

            case 'complete':
              setMessages(prev => prev.map(m =>
                m.id === loadingId || m.id === messageId ? {
                  ...m,
                  id: messageId,
                  content: data.content || m.content,
                  sources: data.sources,
                  metrics: {
                    total_time_ms: data.generation_time || 0,
                    tokens_used: data.tokens_used || 0,
                    sources_used: data.sources?.length || 0,
                    model_used: data.model_used || '',
                  },
                  isLoading: false,
                } : m
              ));
              ws.close();
              break;

            case 'error':
              setMessages(prev => prev.map(m =>
                m.id === loadingId || m.id === messageId ? {
                  ...m,
                  id: messageId,
                  content: `Error: ${data.error || 'Failed to generate response'}`,
                  isLoading: false,
                } : m
              ));
              ws.close();
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
        setMessages(prev => prev.map(m =>
          m.id === loadingId ? {
            ...m,
            content: 'WebSocket connection error. Retrying with polling...',
            isLoading: false,
          } : m
        ));
      };

      ws.onclose = () => {
        console.log('[WebSocket] Disconnected');
      };
    } catch (err) {
      console.error('[WebSocket] Failed to connect:', err);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || !currentWorkspace || loading) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    // Add loading placeholder
    const loadingId = Date.now().toString() + '-loading';
    setMessages(prev => [...prev, {
      id: loadingId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isLoading: true,
    }]);

    try {
      let messageId: string;
      let convId = currentConversation?.id;
      
      if (!currentConversation) {
        // Create new conversation first
        const conversation = await conversationsApi.create({
          workspace_id: currentWorkspace.id,
          title: userMessage.content.slice(0, 50),
        });
        setConversations(prev => [conversation, ...prev]);
        setCurrentConversation(conversation);
        convId = conversation.id;
      }

      // Send message (returns immediately with status: pending)
      const response = await conversationsApi.sendMessage(convId!, {
        query: userMessage.content,
        workspace_id: currentWorkspace.id,
      });

      messageId = response.message_id as string;

      // Connect WebSocket for real-time streaming
      connectWebSocket(messageId, convId!, loadingId);

    } catch (error) {
      setMessages(prev => prev.map(m => 
        m.id === loadingId ? {
          id: Date.now().toString(),
          role: 'assistant',
          content: `Error: ${error instanceof Error ? error.message : 'Failed to generate response'}`,
          timestamp: new Date().toISOString(),
          isLoading: false,
        } : m
      ));
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const deleteConversation = async (id: string) => {
    try {
      await conversationsApi.delete(id);
      setConversations(prev => prev.filter(c => c.id !== id));
      if (currentConversation?.id === id) {
        setCurrentConversation(null);
        setMessages([]);
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      {/* Conversation List */}
      {showConversations && (
        <div className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col">
          <div className="p-4 border-b border-gray-700">
            <button
              onClick={createNewConversation}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2 px-4 rounded-lg text-sm font-medium"
            >
              + New Chat
            </button>
          </div>
          
          <div className="flex-1 overflow-y-auto">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={`p-3 border-b border-gray-700 cursor-pointer hover:bg-gray-700 group ${
                  currentConversation?.id === conv.id ? 'bg-gray-700' : ''
                }`}
                onClick={() => setCurrentConversation(conv)}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm truncate flex-1">
                    {conv.title || 'Untitled'}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteConversation(conv.id);
                    }}
                    className="text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100"
                  >
                    ✕
                  </button>
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {conv.message_count} messages
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Toggle Sidebar */}
        <button
          onClick={() => setShowConversations(!showConversations)}
          className="absolute left-0 top-20 bg-gray-700 px-1 py-2 rounded-r text-xs z-10"
        >
          {showConversations ? '◀' : '▶'}
        </button>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-5xl mb-4">💬</div>
              <h2 className="text-xl font-semibold mb-2">Start a Conversation</h2>
              <p className="text-gray-400 text-sm max-w-md mx-auto">
                Ask questions about your documents. I'll search through your knowledge base
                and provide cited answers.
              </p>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-3xl rounded-lg p-4 ${
                    msg.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 border border-gray-700'
                  }`}
                >
                  {msg.isLoading ? (
                    <div className="flex items-center gap-2">
                      <div className="animate-spin w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full" />
                      <span className="text-gray-400">Thinking...</span>
                    </div>
                  ) : (
                    <>
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                      
                      {/* Sources & Metrics */}
                      {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-gray-700">
                          <div className="text-xs text-gray-400 mb-2">
                            📚 {msg.sources.length} sources used
                          </div>
                          {msg.metrics && (
                            <div className="flex flex-wrap gap-2 text-xs">
                              <span className="bg-gray-700 px-2 py-1 rounded">
                                ⏱️ {msg.metrics.total_time_ms}ms
                              </span>
                              <span className="bg-gray-700 px-2 py-1 rounded">
                                🔍 {msg.metrics.sources_used} sources
                              </span>
                              {msg.verificationScore !== undefined && (
                                <span className={`px-2 py-1 rounded ${
                                  msg.verificationScore >= 0.7 ? 'bg-green-900/50 text-green-400' :
                                  msg.verificationScore >= 0.4 ? 'bg-yellow-900/50 text-yellow-400' :
                                  'bg-red-900/50 text-red-400'
                                }`}>
                                  ✅ {Math.round(msg.verificationScore * 100)}% verified
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-gray-700 bg-gray-800">
          <div className="flex gap-2 max-w-4xl mx-auto">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about your documents..."
              rows={1}
              className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 focus:outline-none focus:border-blue-500 resize-none"
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-6 py-3 rounded-lg font-medium transition-colors"
            >
              {loading ? '...' : 'Send'}
            </button>
          </div>
          <div className="text-center mt-2 text-xs text-gray-500">
            Press Enter to send, Shift+Enter for new line
          </div>
        </div>
      </div>
    </div>
  );
}
