# Muse MCP - Node.js HTTP Shim & MCP Server
FROM node:20-slim

WORKDIR /app

# Install curl and ffmpeg for docker healthcheck & media probing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy package definitions
COPY package*.json ./

# Install dependencies (playwright-core, mcp sdk, remotion, etc.)
RUN npm install --omit=dev

# Copy source code
COPY . .

# Default environment configuration
ENV NODE_ENV=production \
    MUSE_SHIM_HOST=0.0.0.0 \
    MUSE_SHIM_PORT=8787 \
    PORT=8787

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
    CMD curl -f http://localhost:8787/health || exit 1

CMD ["node", "muse-openai-shim.mjs"]
