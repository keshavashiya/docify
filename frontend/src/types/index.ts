// API Types for Docify Frontend

// ============================================================================
// Common Types
// ============================================================================

export interface ApiError {
  detail: string;
  status_code?: number;
}

// ============================================================================
// Workspace Types
// ============================================================================

export interface Workspace {
  id: string;
  name: string;
  workspace_type: 'personal' | 'team' | 'hybrid';
  created_at: string;
  settings: Record<string, unknown>;
}

export interface WorkspaceCreate {
  name: string;
  workspace_type?: 'personal' | 'team' | 'hybrid';
}

// ============================================================================
// Resource Types
// ============================================================================

export interface Resource {
  id: string;
  content_hash: string;
  resource_type: 'pdf' | 'word' | 'excel' | 'markdown' | 'text' | 'url';
  title: string;
  source_url?: string;
  source_path?: string;
  file_size?: number;
  created_at: string;
  last_accessed: string;
  workspace_id: string;
  tags: string[];
  notes?: string;
  chunks_count: number;
  embedding_status: 'pending' | 'processing' | 'complete' | 'error' | 'partial';
  resource_metadata: Record<string, unknown>;
  query_count: number;
  citation_count: number;
}

export interface ResourceListResponse {
  resources: Resource[];
  total: number;
  page: number;
  page_size: number;
}

export interface EmbeddingStatus {
  resource_id: string;
  embedding_status: string;
  chunks_total: number;
  chunks_embedded: number;
  chunks_pending: number;
  progress_percent: number;
  task?: {
    task_id: string;
    state: string;
    info?: Record<string, unknown>;
  };
}

export interface EmbeddingStats {
  pending?: number;
  processing?: number;
  complete?: number;
  error?: number;
  chunks_total: number;
  chunks_embedded: number;
  chunks_pending: number;
}

// ============================================================================
// Conversation Types
// ============================================================================

export interface Conversation {
  id: string;
  workspace_id: string;
  title?: string;
  topic?: string;
  created_at: string;
  updated_at: string;
  entities: string[];
  message_count: number;
  token_usage: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  sources: string[];
  citations: Record<string, unknown>;
  tokens_used?: number;
  generation_time?: number;
  model_used?: string;
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}

export interface ConversationCreate {
  workspace_id: string;
  title?: string;
  topic?: string;
}

// ============================================================================
// Message Generation Types
// ============================================================================

export interface GenerateMessageRequest {
  query: string;
  workspace_id: string;
  conversation_id?: string;
  prompt_type?: 'qa' | 'summary' | 'compare' | 'extract' | 'explain';
  max_context_tokens?: number;
  top_k?: number;
  llm_max_tokens?: number;
  temperature?: number;
  provider?: 'ollama' | 'openai' | 'anthropic';
  model?: string;
  verify_citations?: boolean;
  save_message?: boolean;
}

export interface GenerationMetrics {
  search_time_ms: number;
  rerank_time_ms: number;
  context_time_ms: number;
  prompt_time_ms: number;
  llm_time_ms: number;
  verification_time_ms: number;
  total_time_ms: number;
  tokens_used: number;
  sources_used: number;
  model_used: string;
}

export interface ContextSummary {
  primary_sources: number;
  supporting_sources: number;
  unique_documents: number;
  related_documents: number;
  total_tokens: number;
  has_conflicts: boolean;
}

export interface CitationDetail {
  citation_id: number;
  claim: string;
  source: string;
  source_type: string;
  verified: boolean;
  overlap_score: number;
  matching_text?: string;
  page?: number;
  section?: string;
}

export interface VerificationResult {
  citations: CitationDetail[];
  unverified_claims: string[];
  accuracy_metrics: {
    total_claims: number;
    verified_claims: number;
    verification_score: number;
    has_hallucinations: boolean;
  };
  hallucination_details: string[];
  warnings: string[];
}

export interface GeneratedMessageResponse {
  content: string;
  sources: string[];
  citations: VerificationResult;
  metrics?: GenerationMetrics;
  context_summary?: ContextSummary;
  warnings: string[];
}

// ============================================================================
// Health Types
// ============================================================================

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  timestamp: string;
}
