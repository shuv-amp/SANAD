#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/apps/api"
WEB_DIR="$ROOT_DIR/apps/web"

echo "Resetting SANAD demo state..."
rm -f "$API_DIR/sanad.db"
rm -rf "$API_DIR/storage"
rm -rf "$API_DIR/.pytest_cache"

if [ -d "$WEB_DIR/dist" ]; then
  rm -rf "$WEB_DIR/dist"
fi

(
  cd "$API_DIR"
  source .venv/bin/activate
  python scripts/create_demo_fixtures.py
)

echo "Demo DB/storage cleared and fixtures regenerated."
