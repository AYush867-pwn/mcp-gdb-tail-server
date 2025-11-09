# AIDebugger

A Model Context Protocol (MCP) server that provides tools for analyzing and streaming GDB (GNU Debugger) output to Claude Desktop.

## 🎯 Purpose

This project enables Claude Desktop to:
- Stream GDB output in real-time via WebSocket
- Analyze GDB output with structured parsing
- Provide human-readable explanations for debugging sessions
- Access GDB output files directly

## 📁 Project Structure

```
AIDebugger/
├── start_gdb_streamer.sh      # Entry point for Claude Desktop
├── mcp_entrypoint.py          # Main MCP server (provides 5 tools)
├── mcp_ws_tail_server.py      # WebSocket server (streams gdb.txt)
├── mcp_client_streamer.py   # ⚠️ REDUNDANT: Can be deleted (not used by core system)
├── mock_model_server.py       # Optional: Mock API for testing
├── main.py                    # Optional: HTTP download server
├── gdb.txt                    # GDB output file (monitored)
├── .ws_port                   # Temp file (stores WebSocket port)
└── env/                       # Python virtual environment
```

## 🛠️ Available Tools

1. **gdb-tail** - Get WebSocket URI for real-time streaming
2. **gdb-read-file** - Read gdb.txt content
3. **gdb-file-info** - Get file statistics
4. **gdb-clear-file** - Clear gdb.txt (with confirmation)
5. **gdb-explain** - Analyze and explain GDB output

## 🚀 Setup

1. **Install dependencies**:
   ```bash
   python3 -m venv env
   source env/bin/activate
   pip install websockets python-dotenv flask openai
   ```

2. **Configure Claude Desktop**:
   Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "gdb-streamer": {
         "command": "/bin/bash",
         "args": ["/path/to/AIDebugger/start_gdb_streamer.sh"],
         "env": {
           "FILE_PATH": "/path/to/AIDebugger/gdb.txt",
           "WS_PORT": "8765"
         }
       }
     }
   }
   ```

3. **Start GDB with output redirection**:
   ```bash
   gdb ./program 2>&1 | tee gdb.txt
   ```

4. **Restart Claude Desktop** and enable the "gdb-streamer" connector

## 📖 Usage

In Claude Desktop, you can now:
- "Use gdb-explain to analyze the GDB output"
- "Get file info for gdb.txt"
- "Read the last 50 lines of gdb.txt"
- "Get the WebSocket URI for streaming"

## 📚 Documentation

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed documentation on:
- System architecture
- File descriptions
- Data flow
- Configuration options
- Troubleshooting

## 🔧 Configuration

Create a `.env` file (optional):
```bash
FILE_PATH=./gdb.txt
WS_HOST=0.0.0.0
WS_PORT=8765
SEND_INTERVAL=0.0
READ_CHUNK_DELAY=0.2
```

## 📝 License

MIT

