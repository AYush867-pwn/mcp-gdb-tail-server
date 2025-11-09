#!/usr/bin/env python3
# mcp_ws_tail_server.py
"""
Tailing WebSocket server that streams newly appended lines of a file.
Compatible with various websockets versions (handler supports ws or ws,path).
"""

import asyncio
import json
import sys
from pathlib import Path
import os
import socket
from dotenv import load_dotenv
import websockets
from websockets.http11 import Response
from websockets.datastructures import Headers

# Load .env from script directory
BASE = Path(__file__).parent
load_dotenv(BASE / ".env")

FILE_PATH = Path(os.getenv("FILE_PATH", str(BASE / "gdb.txt")))
HOST = os.getenv("WS_HOST", "0.0.0.0")
PORT = int(os.getenv("WS_PORT", "8765"))
SEND_INTERVAL = float(os.getenv("SEND_INTERVAL", "0"))       # throttle between sends
READ_CHUNK_DELAY = float(os.getenv("READ_CHUNK_DELAY", "0.2"))
PORT_FILE = BASE / ".ws_port"  # File to communicate the actual port to entrypoint
actual_port = PORT  # Global variable to store the actual port being used

async def tail_file_send(ws):
    if not FILE_PATH.exists():
        await ws.send(json.dumps({"type":"error","msg":f"file not found: {FILE_PATH}"}))
        return

    # send meta info
    await ws.send(json.dumps({"type":"meta","filename": FILE_PATH.name, "size": FILE_PATH.stat().st_size}))

    # open file and seek to EOF so we stream only newly appended lines
    with FILE_PATH.open("r", errors="ignore") as f:
        f.seek(0, os.SEEK_END)

        while True:
            line = f.readline()
            if line:
                await ws.send(json.dumps({"type":"line", "data": line.rstrip("\n")}))
                if SEND_INTERVAL:
                    await asyncio.sleep(SEND_INTERVAL)
            else:
                await asyncio.sleep(READ_CHUNK_DELAY)

# Accept either (ws, path) or (ws,) depending on websockets version
async def handler(ws, path=None):
    # path may be None in newer websockets versions
    try:
        remote = getattr(ws, "remote_address", None)
    except Exception:
        remote = None

    print(f"[WS] Client connected: {remote} path={path}")
    try:
        await tail_file_send(ws)
    except websockets.ConnectionClosedOK:
        print(f"[WS] Connection closed cleanly by client: {remote}")
    except websockets.ConnectionClosedError as e:
        print(f"[WS] Connection closed with error from client {remote}: {e!r}")
    except Exception as e:
        print(f"[WS] Error while handling client {remote}: {e!r}")
        try:
            await ws.send(json.dumps({"type":"error","msg":str(e)}))
        except:
            pass
    finally:
        print(f"[WS] Client disconnected: {remote}")

def is_port_available(host, port):
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False

def find_available_port(host, start_port, max_attempts=10):
    """Find an available port starting from start_port."""
    for i in range(max_attempts):
        port = start_port + i
        if is_port_available(host, port):
            return port
    return None

def process_request(connection, request):
    """Handle HTTP requests (non-WebSocket) by returning an HTTP response.
    
    This is called by websockets.serve for requests that are not WebSocket upgrades.
    Returns None to proceed with WebSocket handshake, or a Response object for HTTP.
    """
    # Check if this is a WebSocket upgrade request
    # If it is, return None to proceed with WS handshake
    # The websockets library will only call this for non-WebSocket requests,
    # but we check anyway to be safe
    upgrade_header = request.headers.get("Upgrade", "").lower()
    connection_header = request.headers.get("Connection", "").lower()
    
    if "websocket" in upgrade_header and "upgrade" in connection_header:
        return None
    
    # This is a plain HTTP request - return HTTP response
    # Get file info
    file_exists = FILE_PATH.exists()
    file_size = FILE_PATH.stat().st_size if file_exists else 0
    
    # Create JSON response
    response_data = {
        "status": "running",
        "service": "gdb-tail-websocket-server",
        "file": {
            "path": str(FILE_PATH),
            "exists": file_exists,
            "size": file_size
        },
        "websocket": {
            "url": f"ws://localhost:{actual_port}",
            "note": "This is a WebSocket server. Use a WebSocket client to connect."
        }
    }
    
    response_body = json.dumps(response_data, indent=2)
    response_bytes = response_body.encode('utf-8')
    
    # Create Headers object for the response
    response_headers = Headers()
    response_headers["Content-Type"] = "application/json"
    response_headers["Content-Length"] = str(len(response_bytes))
    
    # Return Response object
    return Response(
        status_code=200,
        reason_phrase="OK",
        headers=response_headers,
        body=response_bytes
    )

async def main():
    global actual_port
    # Check if the default port is available
    actual_port = PORT
    if not is_port_available(HOST, PORT):
        print(f"[WARN] Port {PORT} is already in use. Trying to find an available port...", file=sys.stderr, flush=True)
        actual_port = find_available_port(HOST, PORT)
        if actual_port is None:
            print(f"[ERROR] Could not find an available port starting from {PORT}. Please free up port {PORT} or set WS_PORT to a different value.", file=sys.stderr, flush=True)
            sys.exit(1)
        print(f"[INFO] Using port {actual_port} instead of {PORT}", file=sys.stderr, flush=True)
    
    # Write the actual port to a file so the entrypoint can read it
    try:
        PORT_FILE.write_text(str(actual_port))
    except Exception as e:
        print(f"[WARN] Could not write port to {PORT_FILE}: {e}", file=sys.stderr, flush=True)
    
    print(f"[START] Tailing {FILE_PATH} -> ws://{HOST}:{actual_port} (throttling={SEND_INTERVAL}s)")
    print(f"[INFO] HTTP health check available at http://localhost:{actual_port}/", file=sys.stderr, flush=True)
    
    # Start WebSocket server with HTTP request handler
    # The process_request callback will handle HTTP requests
    try:
        async with websockets.serve(handler, HOST, actual_port, process_request=process_request):
            await asyncio.Future()  # run forever
    finally:
        # Clean up port file on exit
        try:
            if PORT_FILE.exists():
                PORT_FILE.unlink()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[INFO] Shutting down.", file=sys.stderr, flush=True)
    except OSError as e:
        print(f"[ERROR] Failed to start server: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
