import axios, { AxiosInstance, AxiosError } from 'axios';
import type {
  Workspace,
  WorkspaceCreate,
  Resource,
  ResourceListResponse,
  EmbeddingStatus,
  EmbeddingStats,
  Conversation,
  ConversationWithMessages,
  ConversationCreate,
  Message,
  GenerateMessageRequest,
  GeneratedMessageResponse,
  HealthResponse,
} from '../types';

// API Base URL
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Create axios instance
const api: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}/api`,
  timeout: 120000, // 2 minutes for LLM calls
  headers: {
    'Content-Type': 'application/json',
  },
});

// Error handler
const handleError = (error: AxiosError): never => {
  if (error.response) {
    const detail = (error.response.data as { detail?: string })?.detail || 'An error occurred';
    throw new Error(detail);
  } else if (error.request) {
    throw new Error('No response from server. Is the backend running?');
  } else {
    throw new Error(error.message);
  }
};

// ============================================================================
// Health API
// ============================================================================

export const healthApi = {
  check: async (): Promise<HealthResponse> => {
    try {
      const response = await api.get<HealthResponse>('/health');
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },
};

// ============================================================================
// Workspaces API
// ============================================================================

export const workspacesApi = {
  list: async (): Promise<Workspace[]> => {
    try {
      const response = await api.get<Workspace[]>('/workspaces');
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  get: async (id: string): Promise<Workspace> => {
    try {
      const response = await api.get<Workspace>(`/workspaces/${id}`);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  create: async (data: WorkspaceCreate): Promise<Workspace> => {
    try {
      const response = await api.post<Workspace>('/workspaces', data);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  delete: async (id: string): Promise<void> => {
    try {
      await api.delete(`/workspaces/${id}`);
    } catch (error) {
      handleError(error as AxiosError);
    }
  },
};

// ============================================================================
// Resources API
// ============================================================================

export const resourcesApi = {
  list: async (workspaceId?: string, skip = 0, limit = 50): Promise<ResourceListResponse> => {
    try {
      const params = new URLSearchParams();
      if (workspaceId) params.append('workspace_id', workspaceId);
      params.append('skip', skip.toString());
      params.append('limit', limit.toString());
      
      const response = await api.get<ResourceListResponse>(`/resources?${params}`);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  get: async (id: string): Promise<Resource> => {
    try {
      const response = await api.get<Resource>(`/resources/${id}`);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  upload: async (
    file: File,
    workspaceId?: string,
    tags?: string[],
    notes?: string
  ): Promise<Resource> => {
    try {
      const formData = new FormData();
      formData.append('file', file);
      if (workspaceId) formData.append('workspace_id', workspaceId);
      if (tags && tags.length > 0) formData.append('tags', tags.join(','));
      if (notes) formData.append('notes', notes);

      const response = await api.post<Resource>('/resources/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 300000, // 5 minutes for large files
      });
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  delete: async (id: string): Promise<void> => {
    try {
      await api.delete(`/resources/${id}`);
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  getEmbeddingStatus: async (id: string): Promise<EmbeddingStatus> => {
    try {
      const response = await api.get<EmbeddingStatus>(`/resources/${id}/embedding-status`);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  triggerEmbeddings: async (id: string): Promise<{ message: string; task_id: string }> => {
    try {
      const response = await api.post<{ message: string; task_id: string }>(
        `/resources/${id}/generate-embeddings`
      );
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  getEmbeddingStats: async (): Promise<EmbeddingStats> => {
    try {
      const response = await api.get<EmbeddingStats>('/resources/stats/embeddings');
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  getPendingEmbeddings: async (): Promise<{ count: number; resources: Resource[] }> => {
    try {
      const response = await api.get<{ count: number; resources: Resource[] }>(
        '/resources/pending-embeddings'
      );
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },
};

// ============================================================================
// Conversations API
// ============================================================================

export const conversationsApi = {
  list: async (workspaceId?: string, skip = 0, limit = 20): Promise<Conversation[]> => {
    try {
      const params = new URLSearchParams();
      if (workspaceId) params.append('workspace_id', workspaceId);
      params.append('skip', skip.toString());
      params.append('limit', limit.toString());
      
      const response = await api.get<Conversation[]>(`/conversations?${params}`);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  get: async (id: string): Promise<ConversationWithMessages> => {
    try {
      const response = await api.get<ConversationWithMessages>(`/conversations/${id}`);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  create: async (data: ConversationCreate): Promise<Conversation> => {
    try {
      const response = await api.post<Conversation>('/conversations', data);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  delete: async (id: string): Promise<void> => {
    try {
      await api.delete(`/conversations/${id}`);
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  getMessages: async (id: string, skip = 0, limit = 50): Promise<Message[]> => {
    try {
      const response = await api.get<Message[]>(
        `/conversations/${id}/messages?skip=${skip}&limit=${limit}`
      );
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  sendMessage: async (
    conversationId: string,
    request: GenerateMessageRequest
  ): Promise<GeneratedMessageResponse> => {
    try {
      const response = await api.post<GeneratedMessageResponse>(
        `/conversations/${conversationId}/messages`,
        request
      );
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  generate: async (request: GenerateMessageRequest): Promise<GeneratedMessageResponse> => {
    try {
      const response = await api.post<GeneratedMessageResponse>(
        '/conversations/generate',
        request
      );
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  getMessageStatus: async (
    conversationId: string,
    messageId: string
  ): Promise<any> => {
    try {
      const response = await api.get(
        `/conversations/${conversationId}/messages/${messageId}/status`
      );
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  regenerate: async (
    messageId: string,
    options?: { temperature?: number; model?: string; provider?: string }
  ): Promise<GeneratedMessageResponse> => {
    try {
      const response = await api.post<GeneratedMessageResponse>(
        `/conversations/messages/${messageId}/regenerate`,
        { message_id: messageId, ...options }
      );
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },

  export: async (id: string, format: 'json' | 'markdown' = 'json'): Promise<unknown> => {
    try {
      const response = await api.get(`/conversations/${id}/export?format=${format}`);
      return response.data;
    } catch (error) {
      handleError(error as AxiosError);
    }
  },
};

export default api;
