#!/usr/bin/env python3
"""
mcp_entrypoint.py

Minimal MCP stdio entrypoint that:
- spawns the existing websocket tail server (mcp_ws_tail_server.py)
- replies to Claude's `initialize` request
- advertises a tool "gdb-tail"
- on tools.call returns {"connectUri": "ws://127.0.0.1:PORT"} for Claude to connect to

Usage: Claude spawns this script (via your wrapper). It speaks JSON-RPC over STDIO.
"""

import sys
import json
import subprocess
import threading
import time
import os
import re
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
TAIL_SCRIPT = BASE / "mcp_ws_tail_server.py"
WS_PORT = 8765  # default port, but may be overridden if port is in use
PORT_FILE = BASE / ".ws_port"  # File where tail server writes the actual port

# Helper: write JSON-RPC object to stdout (Claude reads this)
def send(obj):
    try:
        s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        sys.stdout.write(s + "\n")
        sys.stdout.flush()
    except Exception as e:
        print(f"[mcp-entry] send error: {e}", file=sys.stderr, flush=True)

# Launch the tail server as a subprocess (so it runs in the venv / env you expect)
def start_tail_subprocess():
    # Use the same python interpreter that launched this entrypoint
    python = sys.executable
    cmd = [python, str(TAIL_SCRIPT)]
    # pass through environment (DOTENV is loaded by tail script itself)
    print(f"[mcp-entry] starting tail subprocess: {cmd}", file=sys.stderr, flush=True)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # Reader threads to forward child stdout/stderr to our stderr for debugging
    def forward_stream(src, name):
        for line in src:
            sys.stderr.write(f"[tail-{name}] {line}")
            sys.stderr.flush()
    threading.Thread(target=forward_stream, args=(p.stdout, "out"), daemon=True).start()
    threading.Thread(target=forward_stream, args=(p.stderr, "err"), daemon=True).start()
    return p

# Start tail server subprocess early
tail_proc = None
try:
    if not TAIL_SCRIPT.exists():
        print(f"[mcp-entry] ERROR: tail script not found at {TAIL_SCRIPT}", file=sys.stderr, flush=True)
    else:
        tail_proc = start_tail_subprocess()
except Exception as e:
    print(f"[mcp-entry] failed to start tail subprocess: {e}", file=sys.stderr, flush=True)
    tail_proc = None

# Advertised tool metadata
TOOL_NAME = "gdb-tail"
TOOL_DESCRIPTION = "Tail the gdb.txt file and stream appended lines to Claude via WS."

# File path from environment or default
FILE_PATH = Path(os.getenv("FILE_PATH", str(BASE / "gdb.txt")))

def get_tools_list():
    """Return the list of available tools."""
    return [
        {
            "name": "gdb-tail",
            "description": "Start streaming the gdb.txt file. Returns a WebSocket URI to connect to for real-time file updates.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "batch_size": {
                        "type": "integer",
                        "description": "Number of lines to batch before sending (not used, for future)",
                        "default": 20
                    },
                    "interval": {
                        "type": "number",
                        "description": "Interval in seconds between batches (not used, for future)",
                        "default": 3.0
                    }
                }
            }
        },
        {
            "name": "gdb-read-file",
            "description": "Read the entire gdb.txt file content.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "integer",
                        "description": "Number of lines to read from the end (0 = read all)",
                        "default": 0
                    }
                }
            }
        },
        {
            "name": "gdb-file-info",
            "description": "Get information about the gdb.txt file (size, exists, last modified).",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "gdb-clear-file",
            "description": "Clear the contents of the gdb.txt file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "Set to true to confirm clearing the file",
                        "default": False
                    }
                },
                "required": ["confirm"]
            }
        },
        {
            "name": "gdb-explain",
            "description": "Analyze and explain the GDB output in simple language with technical findings. Perfect for intermediate and new debugger users.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "detail_level": {
                        "type": "string",
                        "enum": ["simple", "intermediate", "detailed"],
                        "description": "Level of detail in the explanation (simple=basic, intermediate=moderate detail, detailed=comprehensive)",
                        "default": "intermediate"
                    },
                    "focus": {
                        "type": "string",
                        "enum": ["all", "errors", "breakpoints", "assembly", "execution"],
                        "description": "What to focus on in the analysis",
                        "default": "all"
                    }
                }
            }
        }
    ]

# When Claude sends initialize (id present) we reply with capabilities including tools
def handle_initialize(msg):
    result = {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": "gdb-streamer",
            "version": "0.1.0"
        }
    }
    resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
    send(resp)

# Handle tools/list request
def handle_tools_list(msg):
    tools = get_tools_list()
    resp = {
        "jsonrpc": "2.0",
        "id": msg.get("id"),
        "result": {
            "tools": tools
        }
    }
    send(resp)

def get_actual_port():
    """Get the actual port the tail server is using."""
    # Try to read from port file first (tail server writes this)
    # Retry a few times in case the file hasn't been written yet
    for attempt in range(10):
        if PORT_FILE.exists():
            try:
                port = int(PORT_FILE.read_text().strip())
                return port
            except Exception as e:
                if attempt == 9:  # Last attempt
                    print(f"[mcp-entry] Could not read port from {PORT_FILE}: {e}", file=sys.stderr, flush=True)
        if attempt < 9:
            time.sleep(0.1)  # Wait 100ms before retrying
    # Fall back to default port
    return WS_PORT

# Handle different tool calls
def handle_tools_call(msg):
    params = msg.get("params", {})
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    
    if tool_name == "gdb-tail":
        handle_gdb_tail(msg, arguments)
    elif tool_name == "gdb-read-file":
        handle_gdb_read_file(msg, arguments)
    elif tool_name == "gdb-file-info":
        handle_gdb_file_info(msg)
    elif tool_name == "gdb-clear-file":
        handle_gdb_clear_file(msg, arguments)
    elif tool_name == "gdb-explain":
        handle_gdb_explain(msg, arguments)
    else:
        # unknown tool -> error
        resp = {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {
                "code": -32601,
                "message": f"Tool '{tool_name}' not found"
            }
        }
        send(resp)

def handle_gdb_tail(msg, arguments):
    """Handle gdb-tail tool call - returns WebSocket URI."""
    actual_port = get_actual_port()
    connect_uri = f"ws://127.0.0.1:{actual_port}"
    
    result = {
        "content": [
            {
                "type": "text",
                "text": f"WebSocket server is running on {connect_uri}.\n\nConnect to this URI to stream gdb.txt file updates in real-time. The server will send new lines as they are appended to the file."
            }
        ],
        "isError": False
    }
    
    resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
    send(resp)

def handle_gdb_read_file(msg, arguments):
    """Handle gdb-read-file tool call - reads the file content."""
    lines_to_read = arguments.get("lines", 0)
    
    if not FILE_PATH.exists():
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"Error: File {FILE_PATH} does not exist."
                }
            ],
            "isError": True
        }
        resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
        send(resp)
        return
    
    try:
        with FILE_PATH.open("r", errors="ignore") as f:
            all_lines = f.readlines()
            
        if lines_to_read > 0:
            # Read last N lines
            content_lines = all_lines[-lines_to_read:]
            content = "".join(content_lines)
            info = f"Last {len(content_lines)} lines of {FILE_PATH.name}:"
        else:
            # Read all
            content = "".join(all_lines)
            info = f"Full content of {FILE_PATH.name} ({len(all_lines)} lines):"
        
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"{info}\n\n{content}"
                }
            ],
            "isError": False
        }
    except Exception as e:
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"Error reading file: {str(e)}"
                }
            ],
            "isError": True
        }
    
    resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
    send(resp)

def handle_gdb_file_info(msg):
    """Handle gdb-file-info tool call - returns file statistics."""
    if not FILE_PATH.exists():
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"File {FILE_PATH} does not exist."
                }
            ],
            "isError": False
        }
    else:
        try:
            stat = FILE_PATH.stat()
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
            
            # Count lines
            with FILE_PATH.open("r", errors="ignore") as f:
                line_count = sum(1 for _ in f)
            
            info_text = f"""File Information:
Path: {FILE_PATH}
Size: {size} bytes ({size / 1024:.2f} KB)
Lines: {line_count}
Last Modified: {modified}
Exists: Yes"""
            
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": info_text
                    }
                ],
                "isError": False
            }
        except Exception as e:
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error getting file info: {str(e)}"
                    }
                ],
                "isError": True
            }
    
    resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
    send(resp)

def handle_gdb_clear_file(msg, arguments):
    """Handle gdb-clear-file tool call - clears the file."""
    confirm = arguments.get("confirm", False)
    
    if not confirm:
        result = {
            "content": [
                {
                    "type": "text",
                    "text": "Error: You must set 'confirm' to true to clear the file. This is a safety measure."
                }
            ],
            "isError": True
        }
        resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
        send(resp)
        return
    
    try:
        if FILE_PATH.exists():
            FILE_PATH.write_text("")
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"File {FILE_PATH.name} has been cleared successfully."
                    }
                ],
                "isError": False
            }
        else:
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"File {FILE_PATH} does not exist (nothing to clear)."
                    }
                ],
                "isError": False
            }
    except Exception as e:
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"Error clearing file: {str(e)}"
                }
            ],
            "isError": True
        }
    
    resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
    send(resp)

def analyze_gdb_output(content, detail_level="intermediate", focus="all"):
    """Analyze GDB output and extract key information."""
    lines = content.split('\n')
    analysis = {
        "errors": [],
        "warnings": [],
        "breakpoints": [],
        "functions": [],
        "assembly_code": False,
        "execution_status": "unknown",
        "file_info": {},
        "commands_used": [],
        "issues": [],
        "recommendations": []
    }
    
    # Patterns to match
    error_patterns = [
        r"Error: (.+)",
        r"error: (.+)",
        r"Segmentation fault",
        r"Signal (.+) received",
        r"Program received signal",
        r"Fatal error",
        r"Don't know how to run",
        r"The program is not being run",
        r"Undefined command",
        r"No symbol table is loaded",
        r"Unrecognized argument"
    ]
    
    breakpoint_pattern = r"(\d+)\s+breakpoint\s+(\w+)\s+(\w+)\s+([yn])\s+0x([0-9a-fA-F]+)\s+<(.+)>"
    function_pattern = r"Dump of assembler code for function (\w+):"
    assembly_pattern = r"0x[0-9a-fA-F]+\s+<[^>]+>:"
    file_pattern = r"Symbols from \"(.+)\""
    exec_file_pattern = r"`(.+)', file type (.+)"
    entry_point_pattern = r"Entry point: (0x[0-9a-fA-F]+)"
    
    in_assembly = False
    current_function = None
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        # Check for errors
        for pattern in error_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                analysis["errors"].append({
                    "line": i + 1,
                    "message": line_stripped,
                    "type": "error"
                })
                break
        
        # Check for warnings
        if "warning" in line.lower() or "Warning" in line:
            analysis["warnings"].append({
                "line": i + 1,
                "message": line_stripped
            })
        
        # Extract breakpoints
        bp_match = re.search(breakpoint_pattern, line)
        if bp_match:
            bp_num, bp_type, disp, enabled, address, location = bp_match.groups()
            analysis["breakpoints"].append({
                "number": bp_num,
                "type": bp_type,
                "enabled": enabled == "y",
                "address": address,
                "location": location
            })
        
        # Extract function information
        func_match = re.search(function_pattern, line)
        if func_match:
            func_name = func_match.group(1)
            current_function = func_name
            analysis["functions"].append(func_name)
            in_assembly = True
        
        # Detect assembly code
        if re.search(assembly_pattern, line):
            analysis["assembly_code"] = True
        
        # Extract file information
        file_match = re.search(file_pattern, line)
        if file_match:
            analysis["file_info"]["symbol_file"] = file_match.group(1)
        
        exec_match = re.search(exec_file_pattern, line)
        if exec_match:
            analysis["file_info"]["executable"] = exec_match.group(1)
            analysis["file_info"]["file_type"] = exec_match.group(2)
        
        entry_match = re.search(entry_point_pattern, line)
        if entry_match:
            analysis["file_info"]["entry_point"] = entry_match.group(1)
        
        # Check execution status
        if "The program is not being run" in line:
            analysis["execution_status"] = "not_running"
        elif "Program received signal" in line:
            analysis["execution_status"] = "crashed"
        elif "Program exited" in line or "exited normally" in line:
            analysis["execution_status"] = "exited"
        elif "Reading symbols" in line:
            analysis["execution_status"] = "loading"
        
        # Detect common issues
        if "No debugging symbols found" in line:
            analysis["issues"].append("No debugging symbols found - compile with -g flag for better debugging")
        if "Don't know how to run" in line:
            analysis["issues"].append("Program target not configured - use 'run' command or 'target' command")
        if "Undefined command" in line:
            analysis["issues"].append("Invalid GDB command used")
        if "No symbol table is loaded" in line:
            analysis["issues"].append("No symbol table loaded - use 'file' command to load executable")
    
    # Generate recommendations
    if analysis["execution_status"] == "not_running":
        analysis["recommendations"].append("Use 'run' command to start the program execution")
    if not analysis["file_info"].get("executable"):
        analysis["recommendations"].append("Load executable with 'file <path>' command")
    if "No debugging symbols found" in str(analysis["issues"]):
        analysis["recommendations"].append("Recompile with debugging symbols: gcc -g -o program program.c")
    if analysis["breakpoints"]:
        analysis["recommendations"].append("Breakpoints are set - use 'continue' or 'run' to execute until breakpoint")
    if not analysis["breakpoints"] and analysis["execution_status"] == "not_running":
        analysis["recommendations"].append("Consider setting breakpoints with 'break <function>' or 'break <line>' before running")
    
    return analysis

def format_explanation(analysis, detail_level, focus):
    """Format the analysis into a readable explanation."""
    explanation_parts = []
    
    # Header
    explanation_parts.append("## GDB Output Analysis\n")
    explanation_parts.append("This analysis breaks down the GDB debugging session to help you understand what's happening.\n")
    
    # Executive Summary
    if detail_level in ["intermediate", "detailed"]:
        explanation_parts.append("### 📋 Executive Summary\n")
        explanation_parts.append(f"- **Execution Status**: {analysis['execution_status'].replace('_', ' ').title()}\n")
        explanation_parts.append(f"- **Functions Found**: {len(analysis['functions'])}\n")
        explanation_parts.append(f"- **Breakpoints Set**: {len(analysis['breakpoints'])}\n")
        explanation_parts.append(f"- **Errors Detected**: {len(analysis['errors'])}\n")
        explanation_parts.append(f"- **Assembly Code Present**: {'Yes' if analysis['assembly_code'] else 'No'}\n\n")
    
    # File Information
    if analysis['file_info'] and focus in ["all", "execution"]:
        explanation_parts.append("### 📁 File Information\n")
        if analysis['file_info'].get('executable'):
            explanation_parts.append(f"- **Executable**: `{analysis['file_info']['executable']}`\n")
        if analysis['file_info'].get('file_type'):
            explanation_parts.append(f"- **File Type**: {analysis['file_info']['file_type']}\n")
        if analysis['file_info'].get('entry_point'):
            explanation_parts.append(f"- **Entry Point**: {analysis['file_info']['entry_point']}\n")
        if analysis['file_info'].get('symbol_file'):
            explanation_parts.append(f"- **Symbol File**: `{analysis['file_info']['symbol_file']}`\n")
        explanation_parts.append("\n")
    
    # Functions
    if analysis['functions'] and focus in ["all", "assembly", "execution"]:
        explanation_parts.append("### 🔍 Functions Analyzed\n")
        for func in analysis['functions']:
            explanation_parts.append(f"- **{func}()**: Assembly code was dumped for this function\n")
        explanation_parts.append("\n")
        if detail_level == "detailed":
            explanation_parts.append("💡 **What this means**: GDB disassembled these functions to show the machine code instructions.\n\n")
    
    # Breakpoints
    if analysis['breakpoints'] and focus in ["all", "breakpoints", "execution"]:
        explanation_parts.append("### 🎯 Breakpoints\n")
        for bp in analysis['breakpoints']:
            status = "Enabled" if bp['enabled'] else "Disabled"
            explanation_parts.append(f"- **Breakpoint #{bp['number']}**: {status} at `{bp['location']}` (address: 0x{bp['address']})\n")
        explanation_parts.append("\n")
        if detail_level in ["intermediate", "detailed"]:
            explanation_parts.append("💡 **What this means**: Breakpoints pause program execution at specific locations. Use 'continue' to run until the next breakpoint.\n\n")
    
    # Errors
    if analysis['errors'] and focus in ["all", "errors"]:
        explanation_parts.append("### ❌ Errors and Issues\n")
        for error in analysis['errors'][:10]:  # Limit to first 10
            explanation_parts.append(f"- **Line {error['line']}**: {error['message']}\n")
        explanation_parts.append("\n")
        
        # Explain common errors in simple terms
        error_explanations = {
            "Don't know how to run": "GDB doesn't know how to execute the program. Try: `run` or `target exec <file>`",
            "The program is not being run": "The program hasn't been started yet. Use `run` command to begin execution",
            "No symbol table is loaded": "GDB doesn't have debugging information. Load the executable with `file <path>`",
            "No debugging symbols found": "The program was compiled without debug info. Recompile with `-g` flag",
            "Undefined command": "You used a command that GDB doesn't recognize. Check spelling or use `help`",
            "Unrecognized argument": "A command received an invalid argument. Check the command syntax"
        }
        
        if detail_level in ["intermediate", "detailed"]:
            explanation_parts.append("**Simple Explanations**:\n")
            for error in analysis['errors'][:5]:
                for key, explanation in error_explanations.items():
                    if key in error['message']:
                        explanation_parts.append(f"- **{key}**: {explanation}\n")
                        break
            explanation_parts.append("\n")
    
    # Issues
    if analysis['issues'] and focus in ["all", "errors"]:
        explanation_parts.append("### ⚠️ Common Issues Detected\n")
        for issue in analysis['issues']:
            explanation_parts.append(f"- {issue}\n")
        explanation_parts.append("\n")
    
    # Technical Findings
    if detail_level in ["intermediate", "detailed"]:
        explanation_parts.append("### 🔬 Technical Findings\n")
        
        if analysis['assembly_code']:
            explanation_parts.append("- **Assembly Code Present**: The output contains disassembled machine code\n")
            explanation_parts.append("  - This shows the low-level instructions the CPU executes\n")
            explanation_parts.append("  - Useful for understanding program flow and debugging at the machine level\n")
        
        if analysis['breakpoints']:
            explanation_parts.append("- **Breakpoints Configured**: Debugging breakpoints are set up\n")
            explanation_parts.append("  - Breakpoints allow you to pause execution at specific points\n")
            explanation_parts.append("  - Use `info breakpoints` to see all breakpoints\n")
        
        if analysis['execution_status'] == "not_running":
            explanation_parts.append("- **Program Not Running**: The program is loaded but not executing\n")
            explanation_parts.append("  - This is normal when first starting GDB\n")
            explanation_parts.append("  - Use `run` to start execution\n")
        
        explanation_parts.append("\n")
    
    # Recommendations
    if analysis['recommendations']:
        explanation_parts.append("### 💡 Recommended Next Steps\n")
        for i, rec in enumerate(analysis['recommendations'], 1):
            explanation_parts.append(f"{i}. {rec}\n")
        explanation_parts.append("\n")
    
    # Quick Reference
    if detail_level == "detailed":
        explanation_parts.append("### 📚 Quick GDB Command Reference\n")
        explanation_parts.append("- `run` or `r` - Start program execution\n")
        explanation_parts.append("- `break <function>` or `b <function>` - Set breakpoint at function\n")
        explanation_parts.append("- `break <line>` or `b <line>` - Set breakpoint at line number\n")
        explanation_parts.append("- `continue` or `c` - Continue execution until next breakpoint\n")
        explanation_parts.append("- `file <path>` - Load executable file\n")
        explanation_parts.append("- `list` or `l` - Show source code\n")
        explanation_parts.append("- `info breakpoints` - List all breakpoints\n")
        explanation_parts.append("- `info registers` - Show CPU register values\n")
        explanation_parts.append("- `backtrace` or `bt` - Show function call stack\n")
        explanation_parts.append("- `print <variable>` or `p <variable>` - Print variable value\n")
        explanation_parts.append("\n")
    
    return "".join(explanation_parts)

def handle_gdb_explain(msg, arguments):
    """Handle gdb-explain tool call - analyzes and explains GDB output."""
    detail_level = arguments.get("detail_level", "intermediate")
    focus = arguments.get("focus", "all")
    
    if not FILE_PATH.exists():
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"Error: File {FILE_PATH} does not exist. Nothing to analyze."
                }
            ],
            "isError": True
        }
        resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
        send(resp)
        return

    try:
        # Read the file
        with FILE_PATH.open("r", errors="ignore") as f:
            content = f.read()
        
        if not content.strip():
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": "The GDB output file is empty. Run some GDB commands first to generate output."
                    }
                ],
                "isError": False
            }
            resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
            send(resp)
            return
        
        # Analyze the GDB output
        analysis = analyze_gdb_output(content, detail_level, focus)
        
        # Generate explanation
        explanation = format_explanation(analysis, detail_level, focus)
        
        # Add summary at the top for simple level
        if detail_level == "simple":
            summary = f"""## Quick Summary

The GDB session shows:
- {len(analysis['functions'])} function(s) analyzed
- {len(analysis['breakpoints'])} breakpoint(s) set
- {len(analysis['errors'])} error(s) encountered
- Program status: {analysis['execution_status'].replace('_', ' ')}

"""
            explanation = summary + explanation
        
        result = {
            "content": [
                {
                    "type": "text",
                    "text": explanation
                }
            ],
            "isError": False
        }
        
    except Exception as e:
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"Error analyzing GDB output: {str(e)}\n\nTraceback:\n{repr(e)}"
                }
            ],
            "isError": True
        }
    
    resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
    send(resp)

# Simple stdin loop to read lines and process JSON-RPC
def stdin_loop():
    while True:
        line = sys.stdin.readline()
        if not line:
            # EOF (Claude closed transport)
            print("[mcp-entry] stdin closed (EOF). Exiting.", file=sys.stderr, flush=True)
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:
            print(f"[mcp-entry] failed to parse JSON from stdin: {e} line={line}", file=sys.stderr, flush=True)
            continue

        # Handle requests
        method = msg.get("method")
        if method == "initialize":
            handle_initialize(msg)
        elif method == "tools/list":
            handle_tools_list(msg)
        elif method == "tools/call":
            handle_tools_call(msg)
        else:
            # If it's a request with id we should reply with method not implemented
            if msg.get("id") is not None:
                resp = {"jsonrpc":"2.0", "id": msg.get("id"), "error": {"code": -32601, "message": f"Method {method} not implemented"}}
                send(resp)
            else:
                # notification - ignore or log
                print(f"[mcp-entry] received notification: {method}", file=sys.stderr, flush=True)

# Run stdin loop. Keep main thread alive while tail subprocess runs.
try:
    stdin_loop()
finally:
    # Clean up tail subprocess on exit
    if tail_proc:
        try:
            tail_proc.terminate()
            tail_proc.wait(timeout=2)
        except Exception:
            try:
                tail_proc.kill()
            except:
                pass
    print("[mcp-entry] exiting", file=sys.stderr, flush=True)
