# Docify - Local-First AI Second Brain

![Docify - AI Second Brain](./Docify%20-%20AI%20Second%20Brain.png)

**Your personal research assistant that remembers everything you've ever read.**

Docify is an open-source, local-first AI application that lets you upload any resource (PDFs, URLs, documents, images, code), ask questions about them, and receive cited, grounded answers—all while keeping your data completely private.

## ✨ Key Features

- 🔒 **Privacy-First**: All processing happens locally (embeddings, LLM, storage)
- 🧠 **Smart Deduplication**: Content-based fingerprinting prevents duplicate processing
- 📚 **Multi-Format Support**: PDF, URL, Word, Excel, Markdown, images (OCR), code, and more
- 💬 **Cited Answers**: Every response includes citations to source documents
- 🔍 **Hybrid Search**: Combines semantic (vector) and keyword (BM25) search
- 🤖 **Local LLM**: Runs Mistral 7B via Ollama (optional cloud LLM support)
- 🌐 **Workspace Model**: Personal, team, or hybrid collaboration
- 🚀 **One-Command Setup**: Docker Compose orchestration

## 🏗️ Architecture Overview

Docify's RAG pipeline integrates 11 core services:

1. **Resource Ingestion** - Upload, parse, deduplicate
2. **Chunking** - Semantic boundary preservation
3. **Embeddings (Async)** - Vector generation via Celery
4. **Query Expansion** - Better recall with variants
5. **Hybrid Search** - Semantic + keyword (BM25)
6. **Re-Ranking** - 5-factor scoring + conflict detection
7. **Context Assembly** - Token budget management
8. **Prompt Engineering** - Anti-hallucination prompts
9. **LLM Service** - Ollama/OpenAI/Anthropic support
10. **Citation Verification** - Verify claims against sources
11. **Message Generation** - Full pipeline orchestration

See [ARCHITECTURE.md](ARCHITECTURE.md) for complete technical details.

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- 8GB RAM minimum (16GB recommended)
- 20GB disk space (for models and data)

### One-Command Setup ⚡

**macOS / Linux:**
```bash
# Clone the repository
git clone https://github.com/keshavashiya/docify.git
cd docify

# Run the setup script (handles everything!)
./scripts/setup.sh
```

**Windows (PowerShell):**
```powershell
# Clone the repository
git clone https://github.com/keshavashiya/docify.git
cd docify

# Run the setup script (handles everything!)
.\scripts\setup.ps1
```

That's it! The setup script will:
- ✅ Check prerequisites (Docker, memory, disk space)
- ✅ Create environment configuration
- ✅ Start all Docker services
- ✅ Initialize the database with pgvector
- ✅ Download AI models (~4GB, may take 10-15 min)
- ✅ Verify everything is working

**Options:**
```bash
# macOS / Linux
./scripts/setup.sh --skip-models  # Skip model download (faster setup)
./scripts/setup.sh --reset        # Reset everything and start fresh
./scripts/setup.sh --help         # Show all options

# Windows (PowerShell)
.\scripts\setup.ps1 -SkipModels   # Skip model download
.\scripts\setup.ps1 -Reset        # Reset everything
.\scripts\setup.ps1 -Help         # Show all options
```

### After Setup

**macOS / Linux:**
```bash
./scripts/start.sh           # Start Docify (quick start for daily use)
./scripts/start.sh --logs    # Start and follow logs
./scripts/start.sh --stop    # Stop all services
./scripts/start.sh --status  # Show service status
```

**Windows (PowerShell):**
```powershell
.\scripts\start.ps1           # Start Docify
.\scripts\start.ps1 -Logs     # Start and follow logs
.\scripts\start.ps1 -Stop     # Stop all services
.\scripts\start.ps1 -Status   # Show service status
```

### Access

- **Frontend**: http://localhost:3000
- **API Docs & Testing**: http://localhost:8000/docs
- **Health Endpoint**: http://localhost:8000/api/health

### Verify Setup

```bash
# Check if all containers are running
docker-compose ps

# Test API health
curl http://localhost:8000/api/health

# Monitor system resources
docker stats docify-ollama docify-backend

# View logs
docker-compose logs -f backend
docker-compose logs -f celery-worker
```

---

<details>
<summary><b>📋 Manual Setup (Advanced Users)</b></summary>

If you prefer to run each step manually:

```bash
# Clone and enter directory
git clone https://github.com/keshavashiya/docify.git
cd docify

# Copy environment configuration
cp .env.example .env

# Start all services
docker-compose up -d --build

# Wait for services to be healthy (~2-3 minutes)
docker-compose ps

# Initialize database (one-time setup)
docker-compose exec postgres psql -U docify -d docify -c "CREATE EXTENSION IF NOT EXISTS vector"
docker-compose exec backend alembic upgrade head

# Download optimized models (one-time, ~4GB total)
docker-compose exec ollama ollama pull mistral:7b-instruct-q4_0
docker-compose exec ollama ollama pull all-minilm:22m

# Restart services with models loaded
docker-compose restart backend celery-worker
```

</details>

## 🛠️ Local Development

### Backend (Python/FastAPI)

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start development server (requires running docker-compose services)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend (React/TypeScript)

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

## 📦 Tech Stack

**Backend**
- FastAPI (Python 3.10+)
- PostgreSQL 15+ with pgvector
- Celery + Redis (async tasks)
- Ollama (local LLM: mistral:7b-instruct-q4_0, all-minilm:22m)
- sentence-transformers optional (OpenAI/Anthropic support)

**Frontend**
- React 18+ with TypeScript
- Vite, Tailwind CSS
- React Query, Zustand

**Infrastructure**
- Docker & Docker Compose
- Alembic (database migrations)

## 📖 API Usage

### Upload a Resource

```bash
curl -X POST "http://localhost:8000/api/resources/upload" \
  -F "file=@research_paper.pdf" \
  -F "workspace_id=<your-workspace-id>"
```

### Search

```bash
curl -X POST "http://localhost:8000/api/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is RAG?", "workspace_id": "<id>"}'
```

### Ask Questions

```bash
curl -X POST "http://localhost:8000/api/conversations/<id>/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "Explain the main findings", "role": "user"}'
```

## 🐳 Docker & Troubleshooting

### Common Commands

```bash
# Start all services
docker-compose up -d

# View logs (all services)
docker-compose logs -f

# View logs for specific service
docker-compose logs -f backend
docker-compose logs -f celery-worker

# Stop all services
docker-compose down

# Stop and remove data (WARNING: deletes all data)
docker-compose down -v

# Restart specific service
docker-compose restart backend
```

### Port Conflicts

If you get "port already in use" errors:

```bash
# PostgreSQL: Docify uses 5433 (standard is 5432)
# Redis: Docify uses 6380 (standard is 6379)
# Backend: Docify uses 8000
# Frontend: Docify uses 3000
# Ollama: Docify uses 11434

# Check what's using a port (macOS/Linux)
lsof -i :8000

# Kill process (if needed)
kill -9 <PID>
```

### Manual API Testing

Use the built-in API documentation:
- Open http://localhost:8000/docs in your browser
- Try requests directly in Swagger UI
- All endpoints are documented with request/response schemas

Alternatively, use curl:
```bash
# Health check
curl http://localhost:8000/api/health

# List workspaces
curl http://localhost:8000/api/workspaces

# Create workspace
curl -X POST http://localhost:8000/api/workspaces \
  -H "Content-Type: application/json" \
  -d '{"name":"My Workspace","workspace_type":"personal"}'
```

## 📄 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Powered by [Ollama](https://ollama.ai/)
- Vector search by [pgvector](https://github.com/pgvector/pgvector)
- Embeddings by [sentence-transformers](https://www.sbert.net/)

---

**Made with ❤️ for researchers, students, and knowledge workers**
