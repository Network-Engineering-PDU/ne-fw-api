import logging
import ipaddress

from ttne import utils
from ttne.network_type import NetworkType


logger = logging.getLogger(__name__)


class NetworkConfig():

    WIFI_CONN = "ble-wifi-conn"
    ETH_CONN = "ble-eth-conn"

    def __init__(self):
        self.ip = None
        self.mask = None
        self.gateway = None
        self.dns1 = None
        self.dns2 = None
        self.type = None
        self.ssid = None
        self.psk = None
        self.reset()
    
    def reset(self):
        self.ip = ""
        self.mask = ""
        self.gateway = ""
        self.dns1 = ""
        self.dns2 = ""
        self.type = NetworkType.UNCONF
        self.ssid = ""
        self.psk = ""

    def is_static(self):
        return NetworkType.is_static(self.type)

    def is_ethernet(self):
        return (self.type == NetworkType.ETH_DHCP
            or self.type == NetworkType.ETH_STATIC)

    def is_wifi(self):
        return (self.type == NetworkType.WIFI_DHCP
            or self.type == NetworkType.WIFI_STATIC)

    async def get_mac(self, iface):
        retval, output = await utils.shell(f"nmcli -t -f GENERAL.HWADDR d show {iface}")
        mac = ""
        if "GENERAL.HWADDR" in output:
            mac = output.split(":",1)[1].strip()
        return mac

    async def _get_ip_from_if(self, iface):
        retval, output = await utils.shell(f"nmcli -t d show {iface}")
        ip = None
        for l in output.split("\n"):
            if "IP4.ADDRESS[1]" in l:
                ip = l.split(":",1)[1].strip()
            if "IP4.GATEWAY" in l:
                self.gateway = l.split(":",1)[1].strip()

        if ip is None:
            return False

        iface_ip = ipaddress.IPv4Interface(ip)
        self.ip = str(iface_ip.ip)
        self.mask = str(iface_ip.netmask)
        return True

    async def _get_active_eth_if(self):
        for iface in NetworkType.get_available_eth_interfaces():
            retval, output = await utils.shell(
                f"nmcli -t -f GENERAL.STATE d show {iface}"
            )
            if retval == 0 and "connected" in output:
                return iface
        return None


    async def get_current_ip(self):
        retval, output = await utils.shell(f"nmcli -t con show {self.ETH_CONN}")
        if retval == 0: # Static ethernet is configured
            self.type = NetworkType.ETH_STATIC
            retval, output = await utils.shell(f"nmcli -t -f GENERAL.STATE con show {self.ETH_CONN}")
            if "activated" in output:
                iface = await self._get_active_eth_if()
                if iface is not None and await self._get_ip_from_if(iface):
                    return

        retval, output = await utils.shell(f"nmcli -t con show {self.WIFI_CONN}")
        if retval == 0: # Wifi is configured
            retval, output = await utils.shell(f"nmcli -t -f ipv4.method c show {self.WIFI_CONN}")
            if "auto" in output:
                self.type = NetworkType.WIFI_DHCP
            else:
                self.type = NetworkType.WIFI_STATIC
            retval, output = await utils.shell(f"nmcli -t -f GENERAL.STATE con show {self.WIFI_CONN}")
            if "activated" in output:
                iface = NetworkType.to_interface(self.type)
                await self._get_ip_from_if(iface)
                return

        # In other cases the connection is dhcp
        self.type = NetworkType.ETH_DHCP
        iface = await self._get_active_eth_if()
        if iface is not None:
            await self._get_ip_from_if(iface)
            return

    async def get_wifi_ssid(self):
        retval, output = await utils.shell(f"nmcli -t -f 802-11-wireless.ssid con show {self.WIFI_CONN}")
        if retval == 0:
            self.ssid = output.split(":",1)[1].strip()

    async def get_static(self):
        # Con only exist if is static
        retval, output = await utils.shell(f"nmcli -t con show {self.ETH_CONN}")
        if retval == 0:
            self.type = NetworkType.ETH_STATIC

    async def set_wifi(self):
        logger.info("Set WiFi")
        retval, output = await utils.shell(f"nmcli con del {self.WIFI_CONN}")
        retval, output = await utils.shell(f"nmcli connection add type wifi ifname '*' con-name '{self.WIFI_CONN}' ssid '{self.ssid}' 802-11-wireless-security.key-mgmt 'wpa-psk' 802-11-wireless-security.psk '{self.psk}' connection.autoconnect yes")
        retval, output = await utils.shell(f"nmcli con up {self.WIFI_CONN}")

    async def set_ethernet(self):
        logger.info("Set Ethernet")
        retval, output = await utils.shell(f"nmcli con del {self.ETH_CONN}")

        if self.is_static():
            iface = NetworkType.to_interface(self.type)
            iface_ip = ipaddress.IPv4Interface(f"{self.ip}/{self.mask}")
            retval, output = await utils.shell(f"nmcli connection add type ethernet con-name ble-eth-conn ifname {iface} ip4 {str(iface_ip)} gw4 {self.gateway} ipv4.dns '{self.dns1},{self.dns2}'")
            retval, output = await utils.shell(f"nmcli con up {self.ETH_CONN}")

    async def save(self):
        if self.is_ethernet():
            await self.set_ethernet()
        elif self.is_wifi():
            await self.set_wifi()
        else:
            logger.error("Error saving network config")

    async def reset_nw_config(self):
        retval, output = await utils.shell(f"nmcli con del {self.ETH_CONN}")
        if retval != 0:
            logger.warning("Can not delete Ethernet connection (not exist?)")
        retval, output = await utils.shell(f"nmcli con del {self.WIFI_CONN}")
        if retval != 0:
            logger.warning("Can not delete WiFi connection (not exist?)")
        self.reset()
