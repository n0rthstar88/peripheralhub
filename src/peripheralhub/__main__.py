from __future__ import annotations

import sys


def main() -> int:
    """No args: GUI. `service`: background service. `cli ...`: command line (sees the args after `cli`)."""
    if len(sys.argv) > 1 and sys.argv[1] in ("service", "cli"):
        mode = sys.argv[1]
        sys.argv = [f"phub-{mode}", *sys.argv[2:]]
        if mode == "service":
            from peripheralhub import service
            return service.main() or 0
        from peripheralhub import cli
        return cli.main() or 0
    from peripheralhub.ui.app import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
