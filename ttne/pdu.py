from ttne.pmb import Pmb
from ttne.om import Om

class Pdu:
    def __init__(self):
        self.om_devices = {}
        self.om_n = 0
        self.pmb = None

    async def scan_om(self, i2c):
        addrs = await i2c.scan(0x10, 0x30)
        for addr in addrs:
            self.om_devices[self.om_n] = Om(self, i2c, addr, self.om_n)
            self.om_n += 1
        return self.om_devices

    def get_om(self):
        return self.om_devices

    def init_pmb(self, uart):
        self.pmb = Pmb(self, uart)

    def get_pmb(self):
        return self.pmb