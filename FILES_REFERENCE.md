# Files Quick Reference

## 📋 Core Files (Required)

| File | Purpose | When It Runs | Dependencies |
|------|---------|--------------|--------------|
| `start_gdb_streamer.sh` | Wrapper script for Claude Desktop | Auto by Claude Desktop | `mcp_entrypoint.py` |
| `mcp_entrypoint.py` | **Main MCP server** - provides 5 tools | Spawned by wrapper | `mcp_ws_tail_server.py`, `gdb.txt` |
| `mcp_ws_tail_server.py` | WebSocket server - streams file updates | Spawned by entrypoint | `gdb.txt`, writes `.ws_port` |
| `gdb.txt` | GDB output file (monitored) | Written by GDB session | None |

## 🔧 Optional Files

| File | Purpose | When to Use |
|------|---------|-------------|
| `mcp_client_streamer.py` | ~~Streams WS data to OpenAI API~~ | ⚠️ **REDUNDANT - Safe to delete** (Claude has its own model) |
| `mock_model_server.py` | Mock HTTP API server | For testing without OpenAI |
| `main.py` | HTTP download server | If you need HTTP file access |
| `start_streamer.sh` | Legacy wrapper (commented) | Not used |

## 📊 Data Files

| File | Purpose | Created By | Read By |
|------|---------|------------|---------|
| `gdb.txt` | GDB output content | GDB session | `mcp_ws_tail_server.py`, `mcp_entrypoint.py` |
| `.ws_port` | Stores WebSocket port | `mcp_ws_tail_server.py` | `mcp_entrypoint.py` |
| `gdb_explanations.log` | AI explanation logs | `mcp_client_streamer.py` | Manual review |

## 🧪 Test Files

| File | Purpose |
|------|---------|
| `test_ws_client.py` | Test WebSocket connection |
| `test.py` | Unknown/minimal |

## 🔄 Execution Flow

```
1. Claude Desktop → start_gdb_streamer.sh
2. start_gdb_streamer.sh → mcp_entrypoint.py
3. mcp_entrypoint.py → spawns mcp_ws_tail_server.py (subprocess)
4. mcp_ws_tail_server.py → monitors gdb.txt
5. mcp_entrypoint.py → reads gdb.txt (for tools)
```

## 🎯 What Each File Does (One Sentence)

- **start_gdb_streamer.sh**: Activates venv and launches the MCP entrypoint
- **mcp_entrypoint.py**: MCP server that provides 5 tools to Claude Desktop
- **mcp_ws_tail_server.py**: WebSocket server that streams gdb.txt updates
- **gdb.txt**: The file containing GDB output (monitored for changes)
- **mcp_client_streamer.py**: Optional client that sends WS data to OpenAI
- **mock_model_server.py**: Optional mock API for testing
- **main.py**: Optional HTTP server for downloading gdb.txt

## 📝 Key Points

- **Entry Point**: `start_gdb_streamer.sh` (called by Claude Desktop)
- **Main Logic**: `mcp_entrypoint.py` (handles all MCP protocol)
- **Streaming**: `mcp_ws_tail_server.py` (real-time file monitoring)
- **Data Source**: `gdb.txt` (your GDB output)

