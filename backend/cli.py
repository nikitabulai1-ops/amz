"""Command-line entry point for AMZ-VA's existing tool registry.

Lets Claude Code (or anyone at a terminal) call the real calculators in
this project by name instead of recomputing their math by hand in a
response. This is a thin wrapper around agent_tools.dispatch_tool() — the
exact same registry backend/agent.py's chat loop already uses — so there
is only ever one source of truth for what a tool does. No calculation
logic lives here; it only routes to economics.py/inventory.py/sourcing.py/
ppc.py/poa.py/research.py/keepa_client.py, unchanged.

Usage:
    python3 backend/cli.py --list
    python3 backend/cli.py <tool_name> '<json arguments>'
    python3 backend/cli.py <tool_name> --args-file path/to/args.json

Examples:
    python3 backend/cli.py calculate_unit_economics '{"sell_price": 29.99, "unit_cost": 12}'
    python3 backend/cli.py lookup_keepa_product '{"asin": "B0EXAMPLE1"}'
"""

import argparse
import json
import sys

import agent_tools


def _list_tools() -> None:
    for schema in agent_tools.TOOL_SCHEMAS:
        fn = schema["function"]
        params = fn.get("parameters", {})
        required = params.get("required", [])
        all_args = list(params.get("properties", {}).keys())
        print(fn["name"])
        print(f"  {fn['description']}")
        print(f"  required: {', '.join(required) or '(none)'}")
        print(f"  all args: {', '.join(all_args)}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="AMZ-VA tool registry CLI")
    parser.add_argument("tool", nargs="?", help="Tool name, e.g. calculate_unit_economics")
    parser.add_argument("args", nargs="?", help="JSON object of arguments")
    parser.add_argument("--args-file", help="Path to a JSON file of arguments, instead of inline JSON")
    parser.add_argument("--list", action="store_true", help="List every available tool and its arguments")
    parsed = parser.parse_args()

    if parsed.list or not parsed.tool:
        _list_tools()
        return

    if parsed.args_file:
        with open(parsed.args_file) as f:
            arguments = json.load(f)
    elif parsed.args:
        try:
            arguments = json.loads(parsed.args)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON arguments: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        arguments = {}

    result = agent_tools.dispatch_tool(parsed.tool, arguments)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
