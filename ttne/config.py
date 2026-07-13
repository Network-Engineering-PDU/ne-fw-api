class Config:
    VERSION = "0.3.3"
    BOARD_ID = 1
    REV_ID = 1
    # Hardcoded (not os.path.expanduser("~")): processes launched by udev
    # rules (physical USB insert) inherit HOME=/ from sysvinit's PID 1, which
    # resolves "~/.ne" to "/.ne" on the read-only rootfs and crashes.
    TTNE_DIR = "/home/root/.ne"
    DAEMON_PID_FILE = "/tmp/ttne.pid"
    SERVER_PORT = 8001
    OM_UPDATE_FORCE = 0
    PMB_UPDATE_FORCE = 0
    NE_PORT = 80
    NE_IP = "localhost"
    PLATFORM = "cm"

config = Config()
