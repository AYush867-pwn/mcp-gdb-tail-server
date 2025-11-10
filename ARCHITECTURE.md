# AIDebugger - Architecture Documentation

## 📋 Overview

AIDebugger is an MCP (Model Context Protocol) server that provides tools for analyzing and streaming GDB (GNU Debugger) output to Claude Desktop. It enables real-time monitoring of GDB sessions and provides structured analysis of debugging output.

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude Desktop                            │
│  (MCP Client - communicates via JSON-RPC over STDIO)        │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        │ JSON-RPC (STDIN/STDOUT)
                        │
┌───────────────────────▼─────────────────────────────────────┐
│              start_gdb_streamer.sh                          │
│  (Wrapper script - activates venv, launches entrypoint)     │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        │ Executes
                        │
┌───────────────────────▼─────────────────────────────────────┐
│              mcp_entrypoint.py                              │
│  (MCP Server - handles tool requests, spawns WS server)    │
│                                                              │
│  • Handles initialize/tools/list/tools/call                │
│  • Provides 5 tools:                                        │
│    - gdb-tail: Get WebSocket URI                            │
│    - gdb-read-file: Read file content                       │
│    - gdb-file-info: Get file statistics                     │
│    - gdb-clear-file: Clear the file                         │
│    - gdb-explain: Analyze & explain GDB output              │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        │ Spawns subprocess
                        │
┌───────────────────────▼─────────────────────────────────────┐
│          mcp_ws_tail_server.py                               │
│  (WebSocket Server - streams gdb.txt file updates)          │
│                                                              │
│  • Monitors gdb.txt for new lines                           │
│  • Serves WebSocket on port 8765 (or next available)       │
│  • Provides HTTP health check endpoint                      │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        │ Reads/Writes
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    gdb.txt                                  │
│  (GDB output file - written by GDB session)                 │
└─────────────────────────────────────────────────────────────┘

Optional Components:
┌─────────────────────────────────────────────────────────────┐
│          mcp_client_streamer.py                             │
│  (Optional - streams WS data to OpenAI API)                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│          mock_model_server.py                               │
│  (Optional - mock API server for testing)                  │
└─────────────────────────────────────────────────────────────┘
```

## File Descriptions

### Core MCP Server Files

#### 1. `start_gdb_streamer.sh`
**Purpose**: Entry point wrapper script for Claude Desktop MCP integration

**What it does**:
- Activates the Python virtual environment (`env/`)
- Changes to the project directory
- Executes `mcp_entrypoint.py` using the venv's Python interpreter
- Ensures Claude Desktop runs the MCP server in the correct environment

**When it runs**: Automatically by Claude Desktop when the MCP server is enabled

**Configuration**: Hardcoded paths (update if you move the project)

---

#### 2. `mcp_entrypoint.py`  **MAIN FILE**
**Purpose**: MCP protocol server that provides tools to Claude Desktop

**What it does**:
- Implements MCP protocol (JSON-RPC over STDIO)
- Handles `initialize`, `tools/list`, and `tools/call` requests
- Spawns `mcp_ws_tail_server.py` as a subprocess
- Provides 5 tools:
  1. **gdb-tail**: Returns WebSocket URI for streaming
  2. **gdb-read-file**: Reads gdb.txt content (all or last N lines)
  3. **gdb-file-info**: Returns file statistics (size, lines, modified date)
  4. **gdb-clear-file**: Clears gdb.txt (requires confirmation)
  5. **gdb-explain**: Analyzes GDB output with structured parsing and explanations

**Key Functions**:
- `handle_initialize()`: Responds to MCP initialization
- `handle_tools_list()`: Returns list of available tools
- `handle_tools_call()`: Routes tool calls to appropriate handlers
- `analyze_gdb_output()`: Parses GDB output using regex patterns
- `format_explanation()`: Formats analysis into readable markdown

**Dependencies**: 
- `mcp_ws_tail_server.py` (spawns as subprocess)
- Reads `gdb.txt` file
- Writes `.ws_port` file (for port communication)

---

#### 3. `mcp_ws_tail_server.py`
**Purpose**: WebSocket server that streams gdb.txt file updates in real-time

**What it does**:
- Monitors `gdb.txt` for newly appended lines
- Serves WebSocket connections on port 8765 (or next available port)
- Provides HTTP health check endpoint (same port)
- Streams new lines as JSON messages to connected clients
- Handles port conflicts automatically

**Key Features**:
- Auto-detects port conflicts and finds alternative ports
- Writes actual port to `.ws_port` file for entrypoint
- Supports throttling via `SEND_INTERVAL` environment variable
- HTTP endpoint returns server status and file info

**Configuration** (via `.env` or environment):
- `FILE_PATH`: Path to gdb.txt (default: `./gdb.txt`)
- `WS_HOST`: Host to bind (default: `0.0.0.0`)
- `WS_PORT`: Port to use (default: `8765`)
- `SEND_INTERVAL`: Throttle between sends (default: `0`)
- `READ_CHUNK_DELAY`: Delay between file reads (default: `0.2`)

---


### Data Files

#### 8. `gdb.txt`
**Purpose**: The GDB output file that gets monitored

**What it contains**: Output from your GDB debugging session

**How it's created**: Written by your GDB session (redirect output to this file)

**Example GDB command**:
```bash
gdb ./program 2>&1 | tee gdb.txt
```
or in your GDB Session
```bash
set logging enabled
```
#### 10. `.ws_port`
**Purpose**: Temporary file storing the actual WebSocket port

**What it contains**: Port number (e.g., `8765` or `8766`)

**Lifecycle**: Created by `mcp_ws_tail_server.py`, read by `mcp_entrypoint.py`, deleted on server shutdown

---
## 🔄 Data Flow

### 1. MCP Tool Call Flow
```
Claude Desktop
    ↓ (JSON-RPC request: tools/call)
mcp_entrypoint.py
    ↓ (reads gdb.txt or calls analysis)
    ↓ (returns structured result)
Claude Desktop (displays result)
```

### 2. WebSocket Streaming Flow
```
GDB Session
    ↓ (writes to gdb.txt)
mcp_ws_tail_server.py
    ↓ (detects new lines)
    ↓ (sends via WebSocket)
WebSocket Client (receives real-time updates)
```

### 3. Port Communication Flow
```
mcp_ws_tail_server.py
    ↓ (starts, finds available port)
    ↓ (writes port to .ws_port)
mcp_entrypoint.py
    ↓ (reads .ws_port)
    ↓ (returns URI to Claude)
```

## ⚙️ Configuration

### Claude Desktop Config
Location: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "gdb-streamer": {
      "command": "/bin/bash",
      "args": ["/path/to/start_gdb_streamer.sh"],
      "env": {
        "FILE_PATH": "/path/to/gdb.txt",
        "WS_HOST": "0.0.0.0",
        "WS_PORT": "8765"
      }
    }
  }
}
```

### Environment Variables (.env file)
```bash
FILE_PATH=/Users/ayushjoshi/lpu/AIDebugger/gdb.txt
WS_HOST=0.0.0.0
WS_PORT=8765
SEND_INTERVAL=0.0
READ_CHUNK_DELAY=0.2
```

## 🛠️ Dependencies

### Python Packages (in `env/`)
- `websockets`: WebSocket server/client
- `python-dotenv`: Environment variable loading
- `flask`: HTTP server (for main.py, mock_model_server.py)
- `openai`: OpenAI API client (for mcp_client_streamer.py)

## 📊 Tool Details

### gdb-tail
- **Input**: Optional batch_size, interval
- **Output**: WebSocket URI string
- **Use case**: Get connection URI for real-time streaming

### gdb-read-file
- **Input**: `lines` (0 = all, N = last N lines)
- **Output**: File content
- **Use case**: Read GDB output directly

### gdb-file-info
- **Input**: None
- **Output**: File statistics (size, lines, modified date)
- **Use case**: Quick file status check

### gdb-clear-file
- **Input**: `confirm` (boolean, must be true)
- **Output**: Success/error message
- **Use case**: Clear old GDB output

### gdb-explain
- **Input**: 
  - `detail_level`: "simple" | "intermediate" | "detailed"
  - `focus`: "all" | "errors" | "breakpoints" | "assembly" | "execution"
- **Output**: Structured markdown explanation
- **Use case**: Get human-readable analysis of GDB output

##  Quick Start

1. **Setup GDB output**:
   ```bash
   gdb ./program 2>&1 | tee gdb.txt
   ```

2. **Enable in Claude Desktop**:
   - Add server config to `claude_desktop_config.json`
   - Restart Claude Desktop
   - Enable "gdb-streamer" connector

3. **Use tools**:
   - Ask Claude: "Use gdb-explain to analyze the GDB output"
   - Or: "Get file info for gdb.txt"

## 🔍 Troubleshooting

### Port conflicts
- Server auto-finds alternative ports (8766, 8767, etc.)
- Check `.ws_port` file for actual port

### Tools not showing
- Restart Claude Desktop
- Check `mcp_entrypoint.py` logs in Claude Desktop console
- Verify `start_gdb_streamer.sh` has correct paths

### WebSocket not connecting
- Check if `mcp_ws_tail_server.py` is running (subprocess)
- Verify port in `.ws_port` file
- Test with: `curl http://localhost:8765/`

## Notes

- All paths are currently hardcoded (update if moving project)
- The MCP server runs in a subprocess spawned by Claude Desktop
- WebSocket server runs as a subprocess of the MCP entrypoint
- File monitoring uses polling (not inotify/fsevents)

