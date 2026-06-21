from __future__ import annotations

import argparse
import asyncio

from .config import Config
from . import auth


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="imperal-mcp")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("login", help="Log in to your Imperal account in the browser")
    sub.add_parser("logout", help="Log out and remove local credentials")
    args = parser.parse_args(argv)
    cfg = Config.from_env()

    if args.cmd == "login":
        email = auth.login(cfg)
        print(f"Logged in as {email}.")
        return
    if args.cmd == "logout":
        asyncio.run(auth.logout(cfg))
        print("Logged out.")
        return

    # default: run the stdio MCP server
    from .server import build_server
    from .client import ImperalClient
    build_server(ImperalClient(cfg)).run()
