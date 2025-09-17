#!/bin/bash

# build.sh - Build and deploy audiobook converter with FFmpeg 7.1.2

set -e

echo "=================================="
echo "Audiobook Converter - FFmpeg 7.1.2"
echo "Build and Deployment Script"
echo "=================================="

# Configuration
PROJECT_NAME="audiobook-converter"
IMAGE_NAME="audiobook-converter:latest"
CONTAINER_NAME="audiobook-converter-ffmpeg712"

# Unraid paths (adjust as needed)
BASE_PATH="/mnt/user/docker/audiobook-converter"
CONFIG_PATH="${BASE_PATH}/config"
LOGS_PATH="${BASE_PATH}/logs"
INPUT_PATH="/mnt/user/audiobooks/input"
OUTPUT_PATH="/mnt/user/audiobooks/output"

# Functions
create_directories() {
    echo "Creating directory structure..."
    mkdir -p "${CONFIG_PATH}"
    mkdir -p "${LOGS_PATH}"
    mkdir -p "${INPUT_PATH}"
    mkdir -p "${OUTPUT_PATH}"
    mkdir -p "${BASE_PATH}/app"
    echo "✓ Directories created"
}

copy_files() {
    echo "Copying application files..."
    
    # Create app directory structure
    mkdir -p "${BASE_PATH}/app"
    
    # Copy main application files
    cp main.py "${BASE_PATH}/app/"
    cp entrypoint.sh "${BASE_PATH}/app/"
    cp healthcheck.py "${BASE_PATH}/app/"
    
    # Make scripts executable
    chmod +x "${BASE_PATH}/app/entrypoint.sh"
    chmod +x "${BASE_PATH}/app/main.py"
    chmod +x "${BASE_PATH}/app/healthcheck.py"
    
    # Copy configuration files
    if [ ! -f "${CONFIG_PATH}/converter.yaml" ]; then
        cp converter.yaml "${CONFIG_PATH}/"
        echo "✓ Default configuration created"
    else
        echo "ℹ Configuration file exists, keeping current version"
    fi
    
    # Copy Docker files
    cp Dockerfile "${BASE_PATH}/"
    cp docker-compose.yml "${BASE_PATH}/"
    
    echo "✓ Files copied"
}

build_image() {
    echo "Building Docker image..."
    cd "${BASE_PATH}"
    
    # Build the image
    docker build --no-cache -t "${IMAGE_NAME}" .
    
    if [ $? -eq 0 ]; then
        echo "✓ Docker image built successfully"
    else
        echo "✗ Docker image build failed"
        exit 1
    fi
}

stop_existing() {
    echo "Stopping existing container (if running)..."
    if docker ps -q -f name="${CONTAINER_NAME}" | grep -q .; then
        docker stop "${CONTAINER_NAME}"
        echo "✓ Existing container stopped"
    fi
    
    if docker ps -a -q -f name="${CONTAINER_NAME}" | grep -q .; then
        docker rm "${CONTAINER_NAME}"
        echo "✓ Existing container removed"
    fi
}

deploy_container() {
    echo "Deploying container..."
    cd "${BASE_PATH}"
    
    # Start with docker-compose
    docker-compose up -d
    
    if [ $? -eq 0 ]; then
        echo "✓ Container deployed successfully"
    else
        echo "✗ Container deployment failed"
        exit 1
    fi
}

verify_deployment() {
    echo "Verifying deployment..."
    
    # Wait for container to start
    sleep 10
    
    # Check if container is running
    if docker ps -q -f name="${CONTAINER_NAME}" | grep -q .; then
        echo "✓ Container is running"
    else
        echo "✗ Container is not running"
        docker logs "${CONTAINER_NAME}"
        exit 1
    fi
    
    # Check health
    echo "Checking container health..."
    HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' "${CONTAINER_NAME}" 2>/dev/null || echo "no-health-check")
    
    if [ "$HEALTH_STATUS" = "healthy" ] || [ "$HEALTH_STATUS" = "no-health-check" ]; then
        echo "✓ Container is healthy"
    else
        echo "⚠ Container health check pending... (Status: $HEALTH_STATUS)"
    fi
    
    # Check if FFmpeg 7.1.2 is working
    echo "Verifying FFmpeg 7.1.2..."
    FFmpeg_VERSION=$(docker exec "${CONTAINER_NAME}" ffmpeg -version 2>/dev/null | head -1 || echo "FFmpeg check failed")
    
    if echo "$FFmpeg_VERSION" | grep -q "7.1.2"; then
        echo "✓ FFmpeg 7.1.2 confirmed: $FFmpeg_VERSION"
    else
        echo "⚠ FFmpeg version check: $FFmpeg_VERSION"
    fi
    
    # Check libfdk_aac
    echo "Verifying libfdk_aac support..."
    if docker exec "${CONTAINER_NAME}" ffmpeg -hide_banner -h encoder=libfdk_aac >/dev/null 2>&1; then
        echo "✓ libfdk_aac encoder is available"
    else
        echo "✗ libfdk_aac encoder is NOT available"
    fi
}

show_status() {
    echo ""
    echo "=================================="
    echo "Deployment Complete!"
    echo "=================================="
    echo ""
    echo "Container Name: ${CONTAINER_NAME}"
    echo "Image: ${IMAGE_NAME}"
    echo ""
    echo "Paths:"
    echo "  Config:  ${CONFIG_PATH}"
    echo "  Input:   ${INPUT_PATH}"
    echo "  Output:  ${OUTPUT_PATH}"  
    echo "  Logs:    ${LOGS_PATH}"
    echo ""
    echo "Web Interface: http://$(hostname -I | awk '{print $1}'):8080"
    echo ""
    echo "Useful Commands:"
    echo "  View logs:     docker logs -f ${CONTAINER_NAME}"
    echo "  Container CLI: docker exec -it ${CONTAINER_NAME} bash"
    echo "  Stop:          docker stop ${CONTAINER_NAME}"
    echo "  Restart:       docker restart ${CONTAINER_NAME}"
    echo ""
    echo "To add audiobooks:"
    echo "  1. Create a folder in: ${INPUT_PATH}"
    echo "  2. Add MP3 files to the folder"
    echo "  3. Optionally add cover.jpg"
    echo "  4. Watch the logs for processing status"
    echo ""
    echo "Processing workflow:"
    echo "  MP3 files → Beets tagging → FFmpeg M4B → Author/Book/File.m4b"
}

# Main execution
main() {
    echo "Starting deployment process..."
    echo ""
    
    # Check if Docker is available
    if ! command -v docker &> /dev/null; then
        echo "✗ Docker is not installed or not in PATH"
        exit 1
    fi
    
    # Check if docker-compose is available  
    if ! command -v docker-compose &> /dev/null; then
        echo "✗ docker-compose is not installed or not in PATH"
        exit 1
    fi
    
    create_directories
    copy_files
    build_image
    stop_existing
    deploy_container
    verify_deployment
    show_status
}

# Handle command line arguments
case "${1:-deploy}" in
    "clean")
        echo "Cleaning up..."
        docker stop "${CONTAINER_NAME}" 2>/dev/null || true
        docker rm "${CONTAINER_NAME}" 2>/dev/null || true
        docker rmi "${IMAGE_NAME}" 2>/dev/null || true
        echo "✓ Cleanup complete"
        ;;
    "rebuild")
        echo "Rebuilding..."
        docker stop "${CONTAINER_NAME}" 2>/dev/null || true
        docker rm "${CONTAINER_NAME}" 2>/dev/null || true
        docker rmi "${IMAGE_NAME}" 2>/dev/null || true
        main
        ;;
    "deploy"|*)
        main
        ;;
esac