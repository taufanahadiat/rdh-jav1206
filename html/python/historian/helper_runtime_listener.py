#!/usr/bin/env python3
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from systemlog import build_cli_payload, write_event as write_system_event
from historian.listener import main


if __name__ == "__main__":
    write_system_event(
        service="historian",
        component="helper_runtime_listener",
        event="script_started",
        payload=build_cli_payload(sys.argv),
        source_file=__file__,
    )
    try:
        exit_code = main()
        write_system_event(
            service="historian",
            component="helper_runtime_listener",
            event="script_completed",
            payload={"argv": sys.argv, "exit_code": exit_code},
            source_file=__file__,
            status_code=130 if exit_code == 0 else 320,
            severity="low" if exit_code == 0 else "high",
        )
        sys.exit(exit_code)
    except Exception as exc:
        write_system_event(
            service="historian",
            component="helper_runtime_listener",
            event="script_failed",
            payload={"argv": sys.argv, "message": str(exc)},
            source_file=__file__,
            severity="crucial",
            status_code=550,
            message=str(exc),
        )
        raise
