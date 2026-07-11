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
        self.eth_interface = None  # Preferred ethernet port; profile remains usable on either port.
        self.reset()
    
    def reset(self):
        self.ip = "192.168.1.100"
        self.mask = "255.255.255.0"
        self.gateway = "192.168.1.1"
        self.dns1 = "8.8.8.8"
        self.dns2 = ""
        self.type = NetworkType.ETH_STATIC
        self.ssid = ""
        self.psk = ""
        self.eth_interface = None   # Preferred ethernet port; profile remains usable on either port.

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

    async def _get_linked_eth_interfaces(self):
        linked_ifaces = []
        for iface in NetworkType.get_available_eth_interfaces():
            carrier = await utils.read_file(f"/sys/class/net/{iface}/carrier")
            if carrier.strip() == "1":
                linked_ifaces.append(iface)
        return linked_ifaces

    async def _ensure_eth_profile_portable(self):
        retval, output = await utils.shell(
            f"nmcli -g connection.interface-name con show {self.ETH_CONN}"
        )
        if retval != 0:
            return

        pinned_iface = output.strip()
        if pinned_iface in NetworkType.get_available_eth_interfaces():
            logger.info(
                "Clearing pinned ethernet interface %s from %s",
                pinned_iface,
                self.ETH_CONN,
            )

        await utils.shell(
            f"nmcli con modify {self.ETH_CONN} connection.interface-name '' connection.autoconnect yes connection.autoconnect-retries 0"
        )
        await utils.shell("nmcli con reload")

    async def repair_ethernet_activation(self):
        retval, _ = await utils.shell(f"nmcli -t con show {self.ETH_CONN}")
        if retval != 0:
            logger.info("Ethernet profile missing; recreating default profile")
            await self.save()
            return

        await self._ensure_eth_profile_portable()
        linked_ifaces = await self._get_linked_eth_interfaces()
        active_iface = await self._get_active_eth_if()

        if active_iface in linked_ifaces:
            return

        if not linked_ifaces:
            logger.info("No ethernet link detected; taking ethernet profile down")
            await utils.shell(f"nmcli con down {self.ETH_CONN} || true")
            return

        target_iface = linked_ifaces[0]
        logger.info(
            "Repairing ethernet activation: active=%s linked=%s target=%s",
            active_iface,
            ",".join(linked_ifaces),
            target_iface,
        )
        await utils.shell(f"nmcli con down {self.ETH_CONN} || true")
        await utils.shell(
            f"nmcli con up {self.ETH_CONN} ifname '{target_iface}' || nmcli con up {self.ETH_CONN} || true"
        )

    async def get_current_ip(self):
        retval, output = await utils.shell(f"nmcli -t con show {self.ETH_CONN}")
        if retval == 0: # Static ethernet is configured
            await self._ensure_eth_profile_portable()
            self.type = NetworkType.ETH_STATIC
            retval, output = await utils.shell(f"nmcli -t -f GENERAL.STATE con show {self.ETH_CONN}")
            if "activated" in output:
                iface = await self._get_active_eth_if()
                if iface is not None and await self._get_ip_from_if(iface):
                    self.eth_interface = iface  # Store which interface is being used
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

        # No configured connection exists; keep the default static network settings and apply defaults.
        logger.info("No active network connection found; using default static network settings")
        await self.save()
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
        logger.info(f"Set Ethernet on interface {self.eth_interface}")
        # Remove any existing ethernet connection with the configured name
        retval, output = await utils.shell(f"nmcli con del {self.ETH_CONN} || true")
        activation_ifname = self.eth_interface if self.eth_interface else ""

        if self.is_static():
            iface_ip = ipaddress.IPv4Interface(f"{self.ip}/{self.mask}")
            dns_value = self.dns1
            if self.dns2:
                dns_value = f"{self.dns1},{self.dns2}"
            retval, output = await utils.shell(
                f"nmcli connection add type ethernet con-name {self.ETH_CONN} ifname '*' ip4 {str(iface_ip)} gw4 {self.gateway} ipv4.dns '{dns_value}' connection.autoconnect yes connection.autoconnect-retries 0"
            )
        else:
            retval, output = await utils.shell(
                f"nmcli connection add type ethernet con-name {self.ETH_CONN} ifname '*' ipv4.method auto connection.autoconnect yes connection.autoconnect-retries 0"
            )

        if activation_ifname:
            retval, output = await utils.shell(f"nmcli con up {self.ETH_CONN} ifname '{activation_ifname}' || nmcli con up {self.ETH_CONN} || true")
        else:
            retval, output = await utils.shell(f"nmcli con up {self.ETH_CONN} || true")

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
        await self.save()
