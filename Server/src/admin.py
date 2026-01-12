#!/usr/bin/env python3
"""
ZeroSpice Admin CLI Tool

Usage:
  python3 src/admin.py enroll-token              # Generate single-use enrollment token (24h expiry)
  python3 src/admin.py enroll-token --hours 48   # Custom expiration
  python3 src/admin.py enroll-token --uses 5     # Multi-use token
"""

import argparse
import os
import sys
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

# Import token generation function from spice_proxy
# Since we're running as a script, we'll make HTTP request to running server
# OR import directly if running in same process


def generate_token_direct():
    """
    Generate enrollment token directly (imports from spice_proxy module).
    This works when spice_proxy is running and we can import it.
    """
    try:
        # Try to import and call directly
        sys.path.insert(0, os.path.dirname(__file__))
        from spice_proxy import generate_enrollment_token

        return generate_enrollment_token()
    except ImportError:
        return None


def generate_token_standalone(expires_hours=24, max_uses=1):
    """
    Generate enrollment token standalone (doesn't require server running).
    Useful for initial setup or when server is down.
    """
    import json
    import secrets
    from datetime import datetime, timedelta, timezone

    token = secrets.token_urlsafe(32)

    token_data = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(hours=expires_hours)
        ).isoformat(),
        "created_by": "admin",
        "max_uses": max_uses,
        "uses": 0,
        "enrolled_users": [],
    }

    # Store in a tokens file that spice_proxy can read
    tokens_file = ".enrollment_tokens.json"

    tokens = {}
    if os.path.exists(tokens_file):
        with open(tokens_file, "r") as f:
            tokens = json.load(f)

    tokens[token] = token_data

    with open(tokens_file, "w") as f:
        json.dump(tokens, f, indent=2)

    return token, token_data


def main():
    parser = argparse.ArgumentParser(
        description="ZeroSpice Admin CLI Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate single-use 24h token
  python3 src/admin.py enroll-token

  # Generate token valid for 48 hours
  python3 src/admin.py enroll-token --hours 48

  # Generate token that can be used 5 times
  python3 src/admin.py enroll-token --uses 5
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Enroll token command
    enroll_parser = subparsers.add_parser(
        "enroll-token", help="Generate enrollment token for new users"
    )
    enroll_parser.add_argument(
        "--hours", type=int, default=24, help="Token expiration in hours (default: 24)"
    )
    enroll_parser.add_argument(
        "--uses", type=int, default=1, help="Maximum number of uses (default: 1)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "enroll-token":
        # Load environment to get server URL
        load_dotenv()

        proxy_ip = os.getenv("PROXY_IP", "localhost")
        proxy_port = os.getenv("PROXY_HTTP_PORT", "80")

        # Try to determine if we're inside container or outside
        # If PROXY_IP is 0.0.0.0, use localhost
        if proxy_ip == "0.0.0.0":
            proxy_ip = "localhost"

        server_url = f"http://{proxy_ip}:{proxy_port}"

        print("=" * 60)
        print("ZeroSpice Enrollment Token Generator")
        print("=" * 60)
        print()

        # Try API call to running server first
        try:
            response = requests.post(
                "http://127.0.0.1:80/admin/generate-token",
                json={"expires_hours": args.hours, "max_uses": args.uses},
                timeout=5,
            )

            if response.status_code == 201:
                data = response.json()
                token = data["token"]

                print(f"[OK] Enrollment token generated (live server)")
                print()
                print(f"Token:       {token}")
                print(f"Expires:     {data['expires_at']}")
                print(f"Max uses:    {data['max_uses']}")
            else:
                raise Exception("API call failed")

        except Exception as e:
            # Fallback to standalone mode if import fails
            print(f"[WARN] Server not running, using standalone mode")
            print()

            token, token_data = generate_token_standalone(
                expires_hours=args.hours, max_uses=args.uses
            )

            print(f"[OK] Enrollment token generated (file-based)")
            print()
            print(f"Token:       {token}")
            print(f"Expires:     {token_data['expires_at']}")
            print(f"Max uses:    {token_data['max_uses']}")
            print()
            print("[WARN] Note: Server restart required to load this token")
        print()
        print("=" * 60)
        print("Enrollment URL:")
        print("=" * 60)
        print()
        print(f"  {server_url}/enroll?token={token}")
        print()
        print("=" * 60)


if __name__ == "__main__":
    main()
