"""Run with: .venv/bin/python -m horse_racing.operations"""

import argparse

import uvicorn

from horse_racing.operations.app import create_app


def main():
    parser = argparse.ArgumentParser(description="로컬 읽기 전용 운영 대시보드")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    uvicorn.run(
        create_app(port=args.port),
        host="127.0.0.1",
        port=args.port,
        proxy_headers=False,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
