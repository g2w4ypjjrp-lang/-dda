"""``mi-api``: uvicorn ile API sunucusu."""

from __future__ import annotations

import argparse

import uvicorn

from mi_api.app import create_app
from mi_api.config import Settings
from mi_api.logs import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="mi-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    settings = Settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    uvicorn.run(
        create_app(settings),
        host=args.host,
        port=args.port,
        proxy_headers=False,  # istemci adresi yalnızca güvenilen vekillerden (context.client_ip)
        server_header=False,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
