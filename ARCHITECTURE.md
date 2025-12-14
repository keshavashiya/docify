# Docify - Complete Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND (React + TypeScript)              │
│  Upload | Search | Chat | Workspaces | Resource Management      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FASTAPI BACKEND                          │
│  /api/resources | /api/conversations | /api/workspaces          │
└─────────────────────────────────────────────────────────────────┘
       │                      │                      │
       ▼                      ▼                      ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  PostgreSQL  │    │  Redis + Celery  │    │   Ollama     │
│  + pgvector  │    │  (Async Tasks)   │    │  (Local LLM) │
└──────────────┘    └──────────────────┘    └──────────────┘
```

## 11 Core Services

### 1. Resource Ingestion & Parsing
- **Location**: `backend/app/services/parsers/`
- **Purpose**: Upload, detect format, extract text
- **Supported Formats**: PDF, DOCX, XLSX, TXT, HTML, Markdown
- **Features**:
  - Content-based deduplication via SHA-256 hashing
  - Metadata extraction
  - Error recovery with fallback parsing

### 2. Chunking Service
- **File**: `backend/app/services/chunking.py`
- **Purpose**: Split documents into semantic chunks
- **Algorithm**:
  - Respects semantic boundaries (paragraphs, sections)
  - Default chunk size: 512 tokens
  - Overlap: 50 tokens for context continuity
- **Preserves**: Section headers, hierarchy, page numbers

### 3. Embeddings Service (Async)
- **File**: `backend/app/services/embeddings.py`
- **Task**: `backend/app/tasks/embeddings.py`
- **Purpose**: Generate vector embeddings for chunks
- **Model**: `all-minilm:22m` (via Ollama)
- **Dimensions**: 384 (optimized for speed, lightweight)
- **Execution**: Celery async task queue (non-blocking)
- **Storage**: pgvector (HNSW indexing for fast retrieval)
- **Speed**: ~0.5 seconds per chunk

### 4. Query Expansion Service
- **File**: `backend/app/services/query_expansion.py`
- **Purpose**: Generate query variants for better recall
- **Techniques**:
  - Synonym expansion
  - Question reformulation
  - Related concept generation
- **Output**: Multiple expanded queries (default: 3-5 variants)

### 5. Hybrid Search Service
- **File**: `backend/app/services/search.py`
- **Purpose**: Combine semantic and keyword search
- **Components**:
  - **Semantic**: Vector similarity via pgvector (cosine distance)
  - **Keyword**: BM25 ranking (term frequency-inverse document frequency)
- **Ranking**: Reciprocal rank fusion (combines both scores)
- **Returns**: Top-K chunks with relevance scores

### 6. Re-Ranking Service
- **File**: `backend/app/services/reranking.py`
- **Purpose**: Score and rank search results
- **5-Factor Scoring**:
  - Base Relevance: 40% (from hybrid search)
  - Citation Frequency: 15% (how often cited in past)
  - Recency: 15% (document upload date)
  - Specificity: 15% (direct answer match)
  - Source Quality: 15% (document type/credibility)
- **Conflict Detection**: Identifies contradictory sources

### 7. Context Assembly Service
- **File**: `backend/app/services/context_assembly.py`
- **Purpose**: Build optimal context for LLM
- **Strategy**:
  - Token budget (default: 2,000 tokens, optimized)
  - 60% primary sources (top-ranked chunks)
  - 30% supporting context
  - 10% metadata/headers
- **Handles**: Token counting, truncation, ordering
- **Impact**: 40% faster responses with minimal quality loss

### 8. Prompt Engineering Service
- **File**: `backend/app/services/prompt_engineering.py`
- **Purpose**: Craft anti-hallucination prompts
- **Includes**:
  - System prompt with strict instructions
  - Context injection with source markers
  - Citation format requirements
  - Fallback guidance for unknown answers
- **Rules**:
  - ONLY use provided context
  - ALWAYS cite sources [Source N]
  - Say "not available" if unknown
  - Present conflicting views with both sides

### 9. LLM Service
- **File**: `backend/app/services/llm.py`
- **Purpose**: Call language model
- **Supported Providers**:
  - Ollama (local, default: `mistral:7b-instruct-q4_0`, 4-bit quantized)
  - OpenAI (gpt-4, gpt-3.5-turbo)
  - Anthropic (Claude)
- **Hardware Detection**: Auto GPU detection (NVIDIA, AMD, Apple Metal)
- **Configuration**: Env variables for API keys/endpoints, `ENABLE_GPU`, `FORCE_CPU`
- **Performance**: 5-10s response (CPU) / 2-3s (GPU)
- **Streaming**: Support for streaming responses
- **Error Handling**: Fallback, retries, timeout management

### 10. Citation Verification Service
- **File**: `backend/app/services/citation_verification.py`
- **Purpose**: Verify claims against source documents
- **Process**:
  1. Extract cited claims from response
  2. Search for claims in source chunks
  3. Verify or flag mismatches
  4. Rewrite or mark unverified claims
- **Output**: Response with verified citations

### 11. Message Generation Service (Orchestrator)
- **File**: `backend/app/services/message_generation.py`
- **Purpose**: Orchestrate entire RAG pipeline
- **Flow**:
  1. Receive user message
  2. Query expansion
  3. Hybrid search
  4. Re-ranking
  5. Context assembly
  6. Prompt engineering
  7. LLM call
  8. Citation verification
  9. Format response
- **Returns**: Complete message with citations

## Database Schema

### Workspaces
```sql
CREATE TABLE workspaces (
  id UUID PRIMARY KEY,
  name VARCHAR(200),
  workspace_type VARCHAR(20),  -- personal, team, hybrid
  created_at TIMESTAMP,
  settings JSONB
);
```

### Resources
```sql
CREATE TABLE resources (
  id UUID PRIMARY KEY,
  content_hash VARCHAR(64) UNIQUE,  -- SHA-256 for deduplication
  resource_type VARCHAR(50),
  title VARCHAR(500),
  source_url TEXT,
  source_path TEXT,
  file_size BIGINT,
  embedding_status VARCHAR(20),  -- pending, processing, complete, error
  workspace_id UUID REFERENCES workspaces,
  created_at TIMESTAMP,
  chunks_count INT,
  tags TEXT[],
  resource_metadata JSONB
);
```

### Chunks
```sql
CREATE TABLE chunks (
  id UUID PRIMARY KEY,
  resource_id UUID REFERENCES resources,
  sequence INT,
  content TEXT,
  token_count INT,
  section_title VARCHAR(500),
  embedding Vector(384),  -- pgvector extension (all-minilm:22m, 384 dims)
  chunk_metadata JSONB,
  created_at TIMESTAMP
);

CREATE INDEX idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
```

### Conversations
```sql
CREATE TABLE conversations (
  id UUID PRIMARY KEY,
  workspace_id UUID REFERENCES workspaces,
  title VARCHAR(500),
  created_at TIMESTAMP,
  message_count INT,
  token_usage INT
);
```

### Messages
```sql
CREATE TABLE messages (
  id UUID PRIMARY KEY,
  conversation_id UUID REFERENCES conversations,
  role VARCHAR(20),  -- user, assistant
  content TEXT,
  sources UUID[],
  citations JSONB,
  tokens_used INT,
  model_used VARCHAR(100),
  created_at TIMESTAMP
);
```

## API Endpoints

### Resources (`/api/resources`)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/upload` | Upload and process file |
| GET | `/` | List resources |
| GET | `/{id}` | Get resource details |
| DELETE | `/{id}` | Delete resource |
| GET | `/{id}/embedding-status` | Check embedding status |
| POST | `/{id}/generate-embeddings` | Trigger embedding |
| GET | `/stats/embeddings` | Embedding stats |

### Conversations (`/api/conversations`)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/` | Create conversation |
| GET | `/` | List conversations |
| GET | `/{id}` | Get with messages |
| PATCH | `/{id}` | Update conversation |
| DELETE | `/{id}` | Delete conversation |
| POST | `/{id}/messages` | Send message (triggers RAG) |
| POST | `/{id}/messages/{id}/regenerate` | Regenerate response |
| GET | `/{id}/export` | Export (JSON/Markdown) |

### Workspaces (`/api/workspaces`)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/` | Create workspace |
| GET | `/` | List workspaces |
| GET | `/{id}` | Get workspace |
| PATCH | `/{id}` | Update workspace |
| DELETE | `/{id}` | Delete workspace |

## RAG Pipeline Workflow

```
User Query
    │
    ▼
┌──────────────────┐
│ Query Expansion  │ → Generates 3-5 query variants
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Hybrid Search    │ → Semantic + BM25 scoring
├──────────────────┤
│ Results: Top-K   │ → 20-30 candidate chunks
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Re-Ranking       │ → 5-factor scoring
├──────────────────┤
│ Reordered:       │ → Top 5-10 chunks
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Context Assembly │ → Build context (60/30/10 split)
├──────────────────┤
│ Token Budget:    │ → Max 6000 tokens
└──────────────────┘
    │
    ▼
┌──────────────────┐
│Prompt Engineer   │ → Anti-hallucination prompt
├──────────────────┤
│ System Prompt +  │ → Source markers + rules
│ Context + Rules  │
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ LLM Call         │ → Ollama/OpenAI/Anthropic
├──────────────────┤
│ Streaming or     │ → Return response
│ Batch Response   │
└──────────────────┘
    │
    ▼
┌──────────────────┐
│Citation Verify   │ → Check [Source N] in chunks
├──────────────────┤
│ Mark/Rewrite     │ → Verify or flag mismatches
└──────────────────┘
    │
    ▼
Response with Citations
```

## Async Task Processing

### Celery + Redis

```
User uploads file
    │
    ▼
[POST] /api/resources/upload
    │
    ├─ Parse file (blocking)
    │
    ├─ Chunk content (blocking)
    │
    └─ Enqueue Celery task
        │
        ▼ (async, non-blocking)
    Celery Worker
        │
        ├─ Generate embeddings
        │
        ├─ Store in pgvector
        │
        └─ Update status: "complete"

Client can poll: GET /api/resources/{id}/embedding-status
```

## Project Structure

```
docify/
├── backend/
│   ├── app/
│   │   ├── api/                    # FastAPI routes
│   │   │   ├── conversations.py
│   │   │   ├── resources.py
│   │   │   ├── workspaces.py
│   │   │   ├── health.py
│   │   │   └── websocket.py
│   │   ├── core/                   # Configuration
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   └── celery_app.py
│   │   ├── models/
│   │   │   └── models.py           # SQLAlchemy ORM
│   │   ├── schemas/                # Pydantic validation
│   │   │   ├── resource.py
│   │   │   ├── conversation.py
│   │   │   ├── search.py
│   │   │   ├── context.py
│   │   │   ├── citation.py
│   │   │   └── generation.py
│   │   ├── services/               # Business logic
│   │   │   ├── parsers/
│   │   │   │   ├── pdf_parser.py
│   │   │   │   ├── document_parser.py
│   │   │   │   └── url_parser.py
│   │   │   ├── chunking.py
│   │   │   ├── embeddings.py
│   │   │   ├── query_expansion.py
│   │   │   ├── search.py
│   │   │   ├── reranking.py
│   │   │   ├── context_assembly.py
│   │   │   ├── prompt_engineering.py
│   │   │   ├── llm.py
│   │   │   ├── citation_verification.py
│   │   │   ├── message_generation.py
│   │   │   ├── deduplication.py
│   │   │   └── hardware.py
│   │   ├── tasks/
│   │   │   └── embeddings.py       # Celery async task
│   │   ├── utils/
│   │   │   └── helpers.py
│   │   └── main.py                 # FastAPI app
│   ├── alembic/                    # Database migrations
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/             # Reusable components
│   │   │   ├── Upload.tsx
│   │   │   ├── Chat.tsx
│   │   │   ├── Search.tsx
│   │   │   └── ResourceList.tsx
│   │   ├── pages/                  # Page components
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Upload.tsx
│   │   │   └── Chat.tsx
│   │   ├── services/               # API clients
│   │   │   ├── api.ts
│   │   │   ├── resources.ts
│   │   │   ├── conversations.ts
│   │   │   └── workspaces.ts
│   │   ├── types/                  # TypeScript types
│   │   │   └── index.ts
│   │   └── App.tsx
│   ├── package.json
│   ├── tsconfig.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
├── AGENTS.md
├── README.md
└── ARCHITECTURE.md
```

## Key Technologies

| Layer | Technology |
|-------|------------|
| Frontend | React 18+ with TypeScript, Vite, Tailwind CSS, React Query, Zustand |
| Backend | FastAPI, SQLAlchemy 2.0, Celery |
| Database | PostgreSQL 15+ with pgvector, HNSW indexing |
| Embeddings | sentence-transformers/all-mpnet-base-v2 (768 dims) |
| LLM | Ollama (local), OpenAI/Anthropic (optional) |
| Search | Hybrid (semantic + BM25) |
| Task Queue | Celery + Redis |
| Containerization | Docker & Docker Compose |

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://docify:docify@db:5432/docify

# Redis & Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# LLM (Ollama)
OLLAMA_BASE_URL=http://ollama:11434
DEFAULT_MODEL=mistral

# Optional: Cloud LLM
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Embeddings
EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2
EMBEDDING_DIMENSION=768

# Chunking
DEFAULT_CHUNK_SIZE=512
CHUNK_OVERLAP=50

# Upload
MAX_UPLOAD_SIZE=104857600  # 100MB
```

## Security & Privacy

- **Local-First**: All processing on user's machine by default
- **No Cloud**: Optional cloud LLM support (OpenAI/Anthropic) with API keys
- **Data Isolation**: Workspace-based segmentation
- **Encryption**: Optional SSL/TLS for remote access
- **Deduplication**: Content-based (SHA-256), not URL-based
