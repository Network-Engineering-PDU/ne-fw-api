import os

class Config:
    VERSION = "0.2.0"
    BOARD_ID = 1
    REV_ID = 1
    TTNE_DIR = os.path.expanduser("~/.ne")
    DAEMON_PID_FILE = "/tmp/ttne.pid"
    SERVER_PORT = 8001
    OM_UPDATE_FORCE = 0
    PMB_UPDATE_FORCE = 0
    NE_PORT = 80
    NE_IP = "localhost"
    PLATFORM = "cm"

config = Config()
