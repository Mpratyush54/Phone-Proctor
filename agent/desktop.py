"""Launch the Phone-Proctor student desktop with ``python -m agent``."""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Open the Phone-Proctor student desktop.")
    parser.add_argument("--api", default=os.environ.get("PHONE_PROCTOR_API", "http://127.0.0.1:8080"))
    parser.add_argument("--gateway", default=os.environ.get("PHONE_PROCTOR_GATEWAY", "ws://127.0.0.1:8081"))
    args = parser.parse_args()
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        parser.exit(1, "The student desktop needs a graphical display.\n")
    try:
        from screen.student_desktop import launch
    except ImportError as error:
        if error.name and error.name.startswith("PyQt6"):
            parser.exit(1, "Install the student desktop dependencies with pip install PyQt6 PyQt6-WebEngine.\n")
        raise
    launch(args.api, args.gateway)


if __name__ == "__main__":
    main()
