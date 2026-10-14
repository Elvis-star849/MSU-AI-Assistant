#!/usr/bin/env bash
# Start the MSU AI Assistant (Linux/macOS hosts). Usage: scripts/start_assistant.sh [c3_intake_0006|c3_public_0005|baseline] [port]
# The Groq key comes from the environment (GROQ_API_KEY) or the Git-ignored .env file; never commit it.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSU_ASSISTANT_PROFILE="${1:-c3_intake_0006}"
export HF_HUB_OFFLINE=1
exec python -m streamlit run app.py --server.port "${2:-8502}" --server.address "${MSU_BIND_ADDRESS:-127.0.0.1}" \
  --server.headless true --browser.gatherUsageStats false
