from __future__ import annotations

import argparse
import json

from market_intelligence.assistant.foundry import SYSTEM_INSTRUCTIONS, TOOL_SCHEMAS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the REST payload for a versioned Foundry prompt agent."
    )
    parser.add_argument("--model", default="gpt-5.4-mini")
    args = parser.parse_args()

    payload = {
        "description": (
            "NiftyData market intelligence assistant with server-executed "
            "historical market-data functions."
        ),
        "definition": {
            "kind": "prompt",
            "model": args.model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "tools": TOOL_SCHEMAS,
        },
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
