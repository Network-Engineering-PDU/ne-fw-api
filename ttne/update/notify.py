"""CLI hooks for usb_autorun.sh to register update sessions."""

import sys

from .coordinator import UpdateCoordinator, UpdateSource


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: ttne-update-notify {begin|end} [web|usb|ota] [firmware_path] [success|failure]")
        sys.exit(1)

    action = sys.argv[1]

    if action == "begin":
        if len(sys.argv) < 4:
            print("Usage: ttne-update-notify begin <source|auto> <firmware_path>")
            sys.exit(1)
        source_arg = sys.argv[2]
        firmware_path = sys.argv[3]
        if source_arg == "auto":
            source = UpdateCoordinator.source_from_path(firmware_path)
        else:
            source = UpdateSource(source_arg)
        ok, reason = UpdateCoordinator.mark_installing(firmware_path)
        if not ok:
            print(reason)
            sys.exit(2)
        return

    if action == "end":
        if len(sys.argv) < 3:
            print("Usage: ttne-update-notify end <source|auto> [firmware_path] [success|failure]")
            sys.exit(1)
        source_arg = sys.argv[2]
        firmware_path = sys.argv[3] if len(sys.argv) > 3 else ""
        result = sys.argv[4] if len(sys.argv) > 4 else "success"
        if source_arg == "auto":
            if not firmware_path:
                print("firmware_path required with auto")
                sys.exit(1)
            UpdateCoordinator.finish_install(firmware_path, success=result != "failure")
        else:
            UpdateCoordinator.end(UpdateSource(source_arg), success=result != "failure")
        return

    print(f"Unknown action: {action}")
    sys.exit(1)


if __name__ == "__main__":
    main()
