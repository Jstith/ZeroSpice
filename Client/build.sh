#!/bin/bash
# Build script for ZeroSpice Client

set -e

echo "Building ZeroSpice Client..."
echo ""

# Linux build
echo "[1/2] Building for Linux (amd64)..."
GOOS=linux GOARCH=amd64 go build -o zerospice-cli
echo "✓ Created: zerospice-cli"

# Windows build
echo "[2/2] Building for Windows (amd64)..."
GOOS=windows GOARCH=amd64 go build -o zerospice-cli.exe
echo "✓ Created: zerospice-cli.exe"

echo ""
echo "Build complete!"
echo ""
ls -lh zerospice-cli zerospice-cli.exe
