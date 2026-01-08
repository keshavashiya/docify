#!/bin/bash

#===============================================================================
#                         Docify - One-Command Setup
#===============================================================================
# This script sets up everything needed to run Docify for the first time.
# Supports: macOS, Linux
# For Windows: Use scripts/setup.ps1 or WSL
#
# Usage: ./scripts/setup.sh [options]
#   Options:
#     --skip-models    Skip pulling Ollama models (faster, but no LLM features)
#     --reset          Reset everything (WARNING: deletes all data)
#     --help           Show this help message
#===============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
POSTGRES_WAIT_TIMEOUT=60
OLLAMA_WAIT_TIMEOUT=120
BACKEND_WAIT_TIMEOUT=90
MODEL_PULL_TIMEOUT=900  # 15 minutes for model download

# Parse arguments
SKIP_MODELS=false
RESET=false

for arg in "$@"; do
    case $arg in
        --skip-models)
            SKIP_MODELS=true
            shift
            ;;
        --reset)
            RESET=true
            shift
            ;;
        --help)
            head -15 "$0" | tail -11
            exit 0
            ;;
    esac
done

#-------------------------------------------------------------------------------
# Helper Functions
#-------------------------------------------------------------------------------

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "╔═══════════════════════════════════════════════════════════════════════╗"
    echo "║                                                                       ║"
    echo "║       ██████╗  ██████╗  ██████╗██╗███████╗██╗   ██╗                   ║"
    echo "║       ██╔══██╗██╔═══██╗██╔════╝██║██╔════╝╚██╗ ██╔╝                   ║"
    echo "║       ██║  ██║██║   ██║██║     ██║█████╗   ╚████╔╝                    ║"
    echo "║       ██║  ██║██║   ██║██║     ██║██╔══╝    ╚██╔╝                     ║"
    echo "║       ██████╔╝╚██████╔╝╚██████╗██║██║        ██║                      ║"
    echo "║       ╚═════╝  ╚═════╝  ╚═════╝╚═╝╚═╝        ╚═╝                      ║"
    echo "║                                                                       ║"
    echo "║                   Local-First AI Second Brain                         ║"
    echo "║                      One-Command Setup                                ║"
    echo "║                                                                       ║"
    echo "╚═══════════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo ""
    echo -e "${BLUE}${BOLD}[$1/$TOTAL_STEPS]${NC} ${BOLD}$2${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

detect_os() {
    case "$(uname -s)" in
        Darwin*)    echo "macos" ;;
        Linux*)     echo "linux" ;;
        CYGWIN*|MINGW*|MSYS*) echo "windows" ;;
        *)          echo "unknown" ;;
    esac
}

get_available_disk_gb() {
    local os=$(detect_os)
    local available_kb

    if [ "$os" = "macos" ]; then
        # macOS: df outputs 512-byte blocks by default, use -k for KB
        available_kb=$(df -k . | tail -1 | awk '{print $4}')
    else
        # Linux: use -k for KB
        available_kb=$(df -k . | tail -1 | awk '{print $4}')
    fi

    # Convert KB to GB (integer division)
    echo $((available_kb / 1024 / 1024))
}

get_total_memory_gb() {
    local os=$(detect_os)

    if [ "$os" = "macos" ]; then
        # macOS: sysctl returns bytes
        echo $(($(sysctl -n hw.memsize) / 1024 / 1024 / 1024))
    else
        # Linux: /proc/meminfo returns KB
        echo $(($(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024))
    fi
}

wait_for_service() {
    local service=$1
    local check_cmd=$2
    local timeout=$3
    local message=$4
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if eval "$check_cmd" >/dev/null 2>&1; then
            return 0
        fi
        printf "\r${CYAN}⏳${NC} $message (${elapsed}s/${timeout}s)"
        sleep 2
        elapsed=$((elapsed + 2))
    done
    printf "\n"
    return 1
}

check_command() {
    if ! command -v $1 &> /dev/null; then
        print_error "$1 is not installed"
        return 1
    fi
    return 0
}

#-------------------------------------------------------------------------------
# Setup Steps
#-------------------------------------------------------------------------------

TOTAL_STEPS=7

check_prerequisites() {
    print_step 1 "Checking Prerequisites"

    local missing=0
    local os=$(detect_os)

    print_info "Detected OS: $os"

    if [ "$os" = "windows" ]; then
        print_warning "Native Windows detected. Consider using WSL or scripts/setup.ps1"
    fi

    # Check Docker
    if check_command docker; then
        print_success "Docker is installed ($(docker --version | cut -d' ' -f3 | tr -d ','))"
    else
        print_error "Docker is required but not installed"
        echo "  Please install Docker from: https://docs.docker.com/get-docker/"
        missing=1
    fi

    # Check Docker Compose
    if docker compose version &> /dev/null; then
        print_success "Docker Compose is installed ($(docker compose version --short))"
    elif check_command docker-compose; then
        print_success "Docker Compose (legacy) is installed"
    else
        print_error "Docker Compose is required but not installed"
        echo "  Docker Compose should come with Docker Desktop"
        missing=1
    fi

    # Check if Docker daemon is running
    if docker info &> /dev/null; then
        print_success "Docker daemon is running"
    else
        print_error "Docker daemon is not running"
        echo "  Please start Docker Desktop or the Docker service"
        missing=1
    fi

    # Check available disk space (need at least 10GB)
    local available_gb=$(get_available_disk_gb)
    if [ -n "$available_gb" ] && [ "$available_gb" -ge 10 ] 2>/dev/null; then
        print_success "Disk space: ${available_gb}GB available (10GB+ required)"
    elif [ -n "$available_gb" ] && [ "$available_gb" -gt 0 ] 2>/dev/null; then
        print_warning "Low disk space: ${available_gb}GB available (10GB+ recommended)"
    else
        print_info "Could not determine disk space (continuing anyway)"
    fi

    # Check available memory
    local total_mem=$(get_total_memory_gb)
    if [ -n "$total_mem" ] && [ "$total_mem" -ge 8 ] 2>/dev/null; then
        print_success "System memory: ${total_mem}GB (8GB+ required)"
    elif [ -n "$total_mem" ] && [ "$total_mem" -gt 0 ] 2>/dev/null; then
        print_warning "Low memory: ${total_mem}GB (8GB+ recommended for LLM)"
    else
        print_info "Could not determine memory (continuing anyway)"
    fi

    if [ $missing -eq 1 ]; then
        echo ""
        print_error "Prerequisites check failed. Please install missing requirements."
        exit 1
    fi
}

setup_environment() {
    print_step 2 "Setting Up Environment"

    if [ -f .env ]; then
        print_info ".env file already exists"
        read -p "  Overwrite with defaults? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cp .env.example .env
            print_success "Environment file updated from .env.example"
        else
            print_success "Keeping existing .env file"
        fi
    else
        if [ -f .env.example ]; then
            cp .env.example .env
            print_success "Environment file created from .env.example"
        else
            print_error ".env.example not found!"
            exit 1
        fi
    fi

    print_info "You can customize settings in .env later"
}

reset_if_requested() {
    if [ "$RESET" = true ]; then
        print_step 0 "Resetting Everything"
        print_warning "This will delete ALL data including uploaded documents!"
        read -p "  Are you sure? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Stopping and removing containers..."
            $DOCKER_COMPOSE down -v --remove-orphans 2>/dev/null || true
            print_success "All containers and volumes removed"
        else
            print_info "Reset cancelled"
            RESET=false
        fi
    fi
}

start_services() {
    print_step 3 "Starting Docker Services"

    print_info "Building and starting containers (this may take a few minutes on first run)..."

    if $DOCKER_COMPOSE up -d --build 2>&1 | tee /tmp/docify_build.log | grep -E "^(Creating|Building|Starting|Pulling)" ; then
        print_success "Docker containers started"
    else
        # Check if there were actual errors
        if $DOCKER_COMPOSE ps | grep -q "Up"; then
            print_success "Docker containers started"
        else
            print_error "Failed to start containers. Check logs with: docker-compose logs"
            exit 1
        fi
    fi

    echo ""
    print_info "Waiting for services to be healthy..."

    # Wait for PostgreSQL
    if wait_for_service "postgres" \
        "$DOCKER_COMPOSE exec -T postgres pg_isready -U docify" \
        $POSTGRES_WAIT_TIMEOUT \
        "Waiting for PostgreSQL..."; then
        print_success "PostgreSQL is ready"
    else
        print_error "PostgreSQL failed to start"
        exit 1
    fi

    # Wait for Redis
    if wait_for_service "redis" \
        "$DOCKER_COMPOSE exec -T redis redis-cli ping" \
        30 \
        "Waiting for Redis..."; then
        print_success "Redis is ready"
    else
        print_error "Redis failed to start"
        exit 1
    fi

    # Wait for Ollama
    if wait_for_service "ollama" \
        "curl -s http://localhost:11434/api/tags" \
        $OLLAMA_WAIT_TIMEOUT \
        "Waiting for Ollama..."; then
        print_success "Ollama is ready"
    else
        print_warning "Ollama is slow to start (may still be initializing)"
    fi
}

initialize_database() {
    print_step 4 "Initializing Database"

    print_info "Creating pgvector extension..."
    if $DOCKER_COMPOSE exec -T postgres psql -U docify -d docify -c "CREATE EXTENSION IF NOT EXISTS vector" 2>/dev/null; then
        print_success "pgvector extension ready"
    else
        print_warning "pgvector extension may already exist"
    fi

    print_info "Running database migrations..."
    if $DOCKER_COMPOSE exec -T backend alembic upgrade head 2>&1 | tail -5; then
        print_success "Database migrations complete"
    else
        print_error "Database migration failed"
        echo "  Check logs with: docker-compose logs backend"
        exit 1
    fi
}

pull_ollama_models() {
    print_step 5 "Downloading AI Models"

    if [ "$SKIP_MODELS" = true ]; then
        print_warning "Skipping model download (--skip-models flag)"
        print_info "Run without --skip-models later to enable LLM features"
        return
    fi

    print_info "This may take 5-15 minutes depending on your internet speed..."
    print_info "Models will be cached for future runs"
    echo ""

    # Pull embedding model (smaller, ~45MB)
    echo -e "${CYAN}Downloading embedding model (all-minilm:22m)...${NC}"
    if $DOCKER_COMPOSE exec -T ollama ollama pull all-minilm:22m 2>&1 | grep -E "pulling|success|already"; then
        print_success "Embedding model ready"
    else
        print_warning "Embedding model download may have issues"
    fi

    echo ""

    # Pull LLM model (larger, ~4GB)
    echo -e "${CYAN}Downloading LLM model (mistral:7b-instruct-q4_0)...${NC}"
    echo -e "${CYAN}This is a 4GB download - please be patient...${NC}"

    if timeout $MODEL_PULL_TIMEOUT $DOCKER_COMPOSE exec -T ollama ollama pull mistral:7b-instruct-q4_0 2>&1 | grep -E "pulling|success|already"; then
        print_success "LLM model ready"
    else
        print_warning "LLM model download timed out or failed"
        print_info "You can pull it later with: docker-compose exec ollama ollama pull mistral:7b-instruct-q4_0"
    fi
}

finalize_setup() {
    print_step 6 "Finalizing Setup"

    print_info "Restarting services with models loaded..."
    $DOCKER_COMPOSE restart backend celery-worker >/dev/null 2>&1

    # Wait for backend to be healthy
    if wait_for_service "backend" \
        "curl -s http://localhost:8000/api/health" \
        $BACKEND_WAIT_TIMEOUT \
        "Waiting for backend to be ready..."; then
        print_success "Backend is healthy"
    else
        print_warning "Backend is still starting..."
    fi

    print_success "All services configured"
}

show_summary() {
    print_step 7 "Setup Complete!"

    echo ""
    echo -e "${GREEN}${BOLD}╔═══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║                    🎉 Docify is Ready!                                ║${NC}"
    echo -e "${GREEN}${BOLD}╚═══════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BOLD}Access your Docify instance:${NC}"
    echo ""
    echo -e "  ${CYAN}Frontend:${NC}     http://localhost:3000"
    echo -e "  ${CYAN}API Docs:${NC}     http://localhost:8000/docs"
    echo -e "  ${CYAN}Health Check:${NC} http://localhost:8000/api/health"
    echo ""
    echo -e "${BOLD}Useful Commands:${NC}"
    echo ""
    echo -e "  ${YELLOW}Start:${NC}        ./scripts/start.sh   # Start all services"
    echo -e "  ${YELLOW}Stop:${NC}         docker-compose down  # Stop all services"
    echo -e "  ${YELLOW}Logs:${NC}         docker-compose logs -f"
    echo -e "  ${YELLOW}Status:${NC}       docker-compose ps"
    echo ""
    echo -e "${BOLD}Container Status:${NC}"
    $DOCKER_COMPOSE ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || $DOCKER_COMPOSE ps
    echo ""

    if [ "$SKIP_MODELS" = true ]; then
        echo -e "${YELLOW}${BOLD}Note:${NC} LLM models were skipped. Run setup without --skip-models to enable AI features."
        echo ""
    fi

    print_info "Open http://localhost:3000 in your browser to get started!"
}

#-------------------------------------------------------------------------------
# Main Execution
#-------------------------------------------------------------------------------

# Change to project root (script is in scripts/ folder)
cd "$(dirname "$0")/.."

# Determine docker compose command
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

print_banner
reset_if_requested
check_prerequisites
setup_environment
start_services
initialize_database
pull_ollama_models
finalize_setup
show_summary
