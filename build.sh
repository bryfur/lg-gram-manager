#!/bin/bash
#
# Build script for LG Gram Manager (GTK4)
# Uses dpkg-buildpackage to create a proper .deb package
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "========================================"
echo "Building LG Gram Manager (GTK4)"
echo "========================================"

# Check dependencies
echo "Checking build dependencies..."
MISSING_DEPS=""

if ! command -v dpkg-buildpackage >/dev/null 2>&1; then
    MISSING_DEPS="$MISSING_DEPS dpkg-dev"
fi

if ! dpkg -l | grep -q "debhelper"; then
    MISSING_DEPS="$MISSING_DEPS debhelper"
fi

if ! command -v python3 >/dev/null 2>&1; then
    MISSING_DEPS="$MISSING_DEPS python3"
fi

if [ -n "$MISSING_DEPS" ]; then
    echo "Installing missing build dependencies:$MISSING_DEPS"
    sudo apt-get update
    sudo apt-get install -y $MISSING_DEPS
fi

# Make debian/rules executable
chmod +x debian/rules

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build dist build-venv __pycache__ *.egg-info
rm -f ../lg-gram-manager_*.deb ../lg-gram-manager_*.buildinfo ../lg-gram-manager_*.changes

# Build the package
echo "Building .deb package with dpkg-buildpackage..."
dpkg-buildpackage -us -uc -b

# Move the .deb to dist/
mkdir -p dist
mv ../lg-gram-manager_*.deb dist/ 2>/dev/null || true

# Clean up other build artifacts from parent directory
rm -f ../lg-gram-manager_*.buildinfo ../lg-gram-manager_*.changes 2>/dev/null || true

echo ""
echo "========================================"
echo "Build completed successfully!"
echo "========================================"
echo ""
echo "Output:"
ls -la dist/*.deb 2>/dev/null || echo "  Package built in parent directory"
echo ""
echo "Install with:"
echo "  sudo dpkg -i dist/lg-gram-manager_*.deb"
echo ""
echo "Or if dependencies are missing:"
echo "  sudo apt install -f"
echo ""
