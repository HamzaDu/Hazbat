#!/usr/bin/env python3
# Starts the web server (uvicorn). Options uvicorn takes on its command line that come from the config file are added here.
#   python3 -m scripts.serve   (from /app)

import os

from core.varreg import settings


def main():
    command = ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
    if os.getenv("RELOAD"):
        command.append("--reload")
    trusted_proxies = settings.get("app", "trusted_proxies")
    if trusted_proxies:
        command += ["--forwarded-allow-ips", trusted_proxies]
    print(" ".join(command), flush=True)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
