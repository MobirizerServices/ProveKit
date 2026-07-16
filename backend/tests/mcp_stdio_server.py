"""A tiny newline-delimited JSON-RPC MCP server for stdio-transport tests."""
import json
import sys

TOOLS = [{"name": "echo", "description": "echo back", "inputSchema": {"type": "object"}}]


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:
            continue  # notification
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": json.dumps({"echoed": params.get("arguments")})}]}
        else:
            result = {}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
