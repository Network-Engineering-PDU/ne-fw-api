class Config:
    VERSION = "0.5.0"
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
    # True only on boards with one RS-485 transceiver per "485" jack, so each
    # jack can be switched on its own. Current boards wire both jacks to one
    # transceiver (schematic CM V0.1.1, U10), so this stays False for them.
    MODBUS_RTU_PORT_CONTROL = False

config = Config()
