#!/bin/bash

#===============================================================================
#                         Docify - Quick Start
#===============================================================================
# Use this script to start Docify after initial setup.
# Supports: macOS, Linux
# For Windows: Use scripts/start.ps1 or WSL
# For first-time setup, use: ./scripts/setup.sh
#
# Usage: ./scripts/start.sh [options]
#   Options:
#     --build    Rebuild containers before starting
#     --logs     Follow logs after starting
#     --stop     Stop all services
#     --status   Show status of services
#     --help     Show this help message
#===============================================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

# Parse arguments
BUILD=""
FOLLOW_LOGS=false
STOP=false
STATUS=false

for arg in "$@"; do
    case $arg in
        --build)
            BUILD="--build"
            shift
            ;;
        --logs)
            FOLLOW_LOGS=true
            shift
            ;;
        --stop)
            STOP=true
            shift
            ;;
        --status)
            STATUS=true
            shift
            ;;
        --help)
            head -17 "$0" | tail -13
            exit 0
            ;;
    esac
done

# Change to project root (script is in scripts/ folder)
cd "$(dirname "$0")/.."

# Determine docker compose command
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

# Handle --stop
if [ "$STOP" = true ]; then
    echo -e "${YELLOW}${BOLD}⏹ Stopping Docify...${NC}"
    $DOCKER_COMPOSE down
    echo -e "${GREEN}✓ All services stopped${NC}"
    exit 0
fi

# Handle --status
if [ "$STATUS" = true ]; then
    echo -e "${CYAN}${BOLD}📊 Docify Status${NC}"
    echo ""
    $DOCKER_COMPOSE ps
    exit 0
fi

echo ""
echo -e "${CYAN}${BOLD}🚀 Starting Docify...${NC}"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ No .env file found. Running initial setup...${NC}"
    ./scripts/setup.sh
    exit 0
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}✗ Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

# Start services
echo -e "${BLUE}Starting Docker containers...${NC}"
$DOCKER_COMPOSE up -d $BUILD

# Wait a moment for services
echo -e "${BLUE}Waiting for services to be ready...${NC}"
sleep 5

# Check health
if curl -s http://localhost:8000/api/health >/dev/null 2>&1; then
    echo ""
    echo -e "${GREEN}${BOLD}✓ Docify is running!${NC}"
    echo ""
    echo -e "  ${CYAN}Frontend:${NC}     http://localhost:3000"
    echo -e "  ${CYAN}API Docs:${NC}     http://localhost:8000/docs"
    echo ""
else
    echo ""
    echo -e "${YELLOW}⏳ Services are still starting...${NC}"
    echo -e "   Check status with: docker-compose ps"
    echo -e "   View logs with: docker-compose logs -f"
    echo ""
fi

# Show container status
echo -e "${BOLD}Container Status:${NC}"
$DOCKER_COMPOSE ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || $DOCKER_COMPOSE ps

if [ "$FOLLOW_LOGS" = true ]; then
    echo ""
    echo -e "${BLUE}Following logs (Ctrl+C to exit)...${NC}"
    $DOCKER_COMPOSE logs -f
fi
