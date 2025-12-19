import os
import sys
import time
import fcntl
import signal
import logging

logger = logging.getLogger(__name__)

class Daemon:
    def __init__(self, name, pid_file, run, exit_cb=None):
        self.name = name
        self.pid_file = pid_file
        self.pid_fd = None
        self.run = run
        self.exit = exit_cb

    def demonize(self):
        if os.fork() != 0:
            sys.exit(0) # Parent exists
        os.setsid() # Change to new session
        if os.fork() != 0:
            sys.exit(0) # Parent exists again

        os.umask(0o022) # Reset umask
        os.chdir("/") # Change to root directory

        # Redirect stdin, stdout and sterr to /dev/null
        os.close(sys.stdin.fileno())
        os.close(sys.stdout.fileno())
        os.close(sys.stderr.fileno())
        fd = os.open(os.devnull, os.O_RDWR)
        os.dup2(fd, sys.stdout.fileno())
        os.dup2(fd, sys.stderr.fileno())

        pid = self.create_pid_file()
        logger.info(f"Daemon running with PID {pid}")

    def exit_callback(self, signum, _):
        logger.debug("Exit callback")
        self.exit()

    def create_pid_file(self) -> int:
        self.pid_fd = os.open(self.pid_file, os.O_RDWR|os.O_CREAT, 0o664)
        fcntl.lockf(self.pid_fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        pid = os.getpid()
        os.write(self.pid_fd, f"{pid}\n".encode())
        return pid

    def delete_pid_file(self):
        try:
            fcntl.lockf(self.pid_fd, fcntl.LOCK_UN)
            os.close(self.pid_fd)
            os.remove(self.pid_file)
        except:
            #TODO algo?
            pass

    def start(self):
        try:
            self.pid_fd = os.open(self.pid_file, os.O_RDWR|os.O_CREAT)
            fcntl.lockf(self.pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.lockf(self.pid_fd, fcntl.LOCK_UN)
            os.close(self.pid_fd)
        except BlockingIOError:
            print(f"PID file '{self.pid_file}' exists and it's locked.")
            print(f"Is {self.name} daemon already running?")
            sys.exit(1)

        self.demonize()
        signal.signal(signal.SIGTERM, self.exit_callback)
        signal.signal(signal.SIGINT, self.exit_callback)
        try:
            self.run()
        except SystemExit:
            logger.exception("Daemon system exit exception")
        except:
            logger.exception("Deamon run exception")
            raise
        finally:
            logger.info("Daemon stopped")
            self.delete_pid_file()
            # pylint: disable=protected-access
            os._exit(0)
            # pylint: enable=protected-access

    def stop(self, restart=False):
        try:
            with open(self.pid_file) as f:
                pid = int(f.read())
        except FileNotFoundError:
            print(f"PID file '{self.pid_file}' doesn't exists.")
            print(f"{self.name} daemon is not running.")
            if restart:
                print("Starting...")
                return
            sys.exit(1)
        try:
            while os.kill(pid, signal.SIGINT):
                time.sleep(0.2)
        except ProcessLookupError:
            pass

    def restart(self):
        self.stop(restart=True)
        time.sleep(10)
        self.start()
