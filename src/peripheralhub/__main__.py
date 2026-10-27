from __future__ import annotations

import importlib
import sys


def main(argv: list[str] | None = None) -> int:
    """No args: GUI. `service`: background service. `cli ...`: command line (sees the args after `cli`)."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("service", "cli"):
        mode = argv[0]
        sys.argv = [f"phub-{mode}", *argv[1:]]
        try:
            module = importlib.import_module(f"peripheralhub.{mode}")
        except ModuleNotFoundError as e:
            if e.name != f"peripheralhub.{mode}":
                raise
            print(f"{mode} is not available yet", file=sys.stderr)
            return 2
        return module.main() or 0
    from peripheralhub.ui.app import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
