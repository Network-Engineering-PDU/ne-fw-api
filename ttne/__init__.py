import os
import sys

from ttne import utils
from ttne.config import config


def daemon():
    daemon_commands = ("start", "stop", "restart")
    if len(sys.argv) <= 1 or sys.argv[1] not in daemon_commands:
        cmd = os.path.basename(sys.argv[0])
        print("Usage: {} ({})".format(cmd, "|".join(daemon_commands)))
        sys.exit(1)

    utils.config_logger()
    utils.set_threading_exception_handler()

    from ttne.daemon import Daemon
    from ttne.server import Server
    server = Server()
    app = Daemon("ttne", config.DAEMON_PID_FILE, server.run,
        server.exit_trap)
    if sys.argv[1] == "start":
        app.start()
    elif sys.argv[1] == "stop":
        app.stop()
    elif sys.argv[1] == "restart":
        app.restart()
