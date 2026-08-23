import logging
import ipaddress
import os
import json

from ttne import utils
from ttne.network_type import NetworkType


logger = logging.getLogger(__name__)
NETWORK_APPLY_LOCK_FILE = "/tmp/ttne_network_apply.lock"
NETWORK_UI_CONFIG_FILE = "/home/root/.ne/network_ui_config.json"


class NetworkConfig():

    WIFI_CONN = "ble-wifi-conn"
    ETH_CONN = "ble-eth-conn"
    BRIDGE_IFACE = "br0"
    BRIDGE_LAN1_CONN = "ble-eth-bridge-lan1"
    BRIDGE_LAN2_CONN = "ble-eth-bridge-lan2"
    LAN1_CONN = "ble-eth-lan1-conn"
    LAN2_CONN = "ble-eth-lan2-conn"
    LAN1_IFACE = "eth1"
    LAN2_IFACE = "eth0"
    LAN1_ROUTE_TABLE = 101
    LAN2_ROUTE_TABLE = 102
    LAN1_RULE_PRIORITY = 1001
    LAN2_RULE_PRIORITY = 1002
    NW_SINGLE_LAN = 0
    NW_WIFI_ONLY = 1
    NW_DUAL_LAN = 2
    NW_LAN_WIFI = 3

    def __init__(self):
        self.ip = None
        self.mask = None
        self.gateway = None
        self.dns1 = None
        self.dns2 = None
        self.type = None
        self.ssid = None
        self.psk = None
        self.eth_interface = None  # Preferred port for display/route metrics; Single-LAN bridges both ports.
        self.nw_mode = self.NW_SINGLE_LAN
        self.lan1_ip = None
        self.lan1_gateway = None
        self.lan2_ip = None
        self.lan2_gateway = None
        self.wifi_ip = None
        self._dual_lan_policy_initialized = False
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
        self.eth_interface = None   # Preferred port for display/route metrics; Single-LAN bridges both ports.
        self.nw_mode = self.NW_SINGLE_LAN
        self.lan1_ip = "192.168.1.100"
        self.lan1_gateway = "192.168.1.1"
        self.lan2_ip = "192.168.1.200"
        self.lan2_gateway = ""
        self.wifi_ip = ""

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

    async def _read_ip_from_if(self, iface):
        retval, output = await utils.shell(f"nmcli -t d show {iface}")
        if retval != 0:
            return None, None, None

        ip = None
        gateway = None
        for line in output.splitlines():
            if line.startswith("IP4.ADDRESS[1]:"):
                ip = line.split(":", 1)[1].strip()
            elif line.startswith("IP4.GATEWAY:"):
                gateway = line.split(":", 1)[1].strip()

        if ip is None:
            return None, None, gateway

        iface_ip = ipaddress.IPv4Interface(ip)
        return str(iface_ip.ip), str(iface_ip.netmask), gateway

    async def _connection_exists(self, name):
        retval, _ = await utils.shell(f"nmcli -t con show '{name}'")
        return retval == 0

    async def _get_connection_type(self, name):
        retval, output = await utils.exec_command(
            "nmcli", "-g", "connection.type", "connection", "show", name
        )
        if retval != 0:
            return None
        return output.strip()

    async def _single_bridge_is_configured(self):
        if await self._get_connection_type(self.ETH_CONN) != "bridge":
            return False
        return (
            await self._connection_exists(self.BRIDGE_LAN1_CONN)
            and await self._connection_exists(self.BRIDGE_LAN2_CONN)
        )

    async def _get_connection_ipv4_method(self, name):
        retval, output = await utils.exec_command(
            "nmcli", "-g", "ipv4.method", "connection", "show", name
        )
        if retval != 0:
            return None
        return output.strip()

    async def _get_dual_lan_profile_state(self):
        return (
            await self._connection_exists(self.LAN1_CONN),
            await self._connection_exists(self.LAN2_CONN),
        )

    async def _is_dual_lan_configured(self):
        profile_state = await self._get_dual_lan_profile_state()
        if any(profile_state) and not all(profile_state):
            logger.warning(
                "Incomplete dual-LAN configuration detected: LAN1=%s LAN2=%s",
                profile_state[0],
                profile_state[1],
            )
            await self._restore_missing_dual_lan_profiles(profile_state)
            profile_state = await self._get_dual_lan_profile_state()
        # Keep treating a partial setup as dual-LAN so a failed restoration
        # cannot fall through and replace it with the single-LAN profile.
        return any(profile_state)

    def _load_saved_network_config(self):
        try:
            with open(NETWORK_UI_CONFIG_FILE, "r") as config_file:
                data = json.load(config_file)
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _get_saved_network_mode(self, saved_config=None):
        if saved_config is None:
            saved_config = self._load_saved_network_config()
        try:
            return int(saved_config.get("nw_mode"))
        except (AttributeError, TypeError, ValueError):
            return None

    async def _disable_auto_wired_connections(self):
        retval, output = await utils.shell("nmcli -t -f NAME,TYPE con show")
        if retval != 0 or output is None:
            return
        for line in output.splitlines():
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            name, conn_type = parts
            if conn_type == "802-3-ethernet" and name.startswith("Wired connection"):
                await utils.shell(
                    f"nmcli con modify '{name}' connection.autoconnect no || true"
                )

    async def _delete_single_eth_connection(self):
        await utils.shell(f"nmcli con del '{self.BRIDGE_LAN1_CONN}' || true")
        await utils.shell(f"nmcli con del '{self.BRIDGE_LAN2_CONN}' || true")
        await utils.shell(f"nmcli con del '{self.ETH_CONN}' || true")

    async def _delete_dual_lan_connections(self):
        await utils.shell(f"nmcli con del '{self.LAN1_CONN}' || true")
        await utils.shell(f"nmcli con del '{self.LAN2_CONN}' || true")

    async def _delete_wifi_connection(self):
        await utils.shell(f"nmcli con del '{self.WIFI_CONN}' || true")

    async def _get_active_eth_if(self):
        for iface in NetworkType.get_available_eth_interfaces():
            retval, output = await utils.shell(
                f"nmcli -g GENERAL.STATE d show {iface}"
            )
            state = output.strip().split(None, 1)[0] if output else ""
            if retval == 0 and state == "100":
                return iface
        return None

    async def _get_active_connections(self):
        retval, output = await utils.shell(
            "nmcli -t -f NAME,DEVICE connection show --active"
        )
        if retval != 0 or output is None:
            return {}

        active_connections = {}
        for line in output.splitlines():
            name, separator, iface = line.rpartition(":")
            if separator and name and iface:
                active_connections[name] = iface
        return active_connections

    async def _get_linked_eth_interfaces(self):
        linked_ifaces = []
        for iface in NetworkType.get_available_eth_interfaces():
            carrier = await utils.read_file(f"/sys/class/net/{iface}/carrier")
            if carrier.strip() == "1":
                linked_ifaces.append(iface)
        return linked_ifaces

    async def _set_dual_lan_arp_settings(self, enabled):
        arp_ignore = 1 if enabled else 0
        arp_announce = 2 if enabled else 0
        success = True
        for iface in (self.LAN1_IFACE, self.LAN2_IFACE):
            retval, _ = await utils.exec_command(
                "sysctl", "-q", "-w",
                f"net.ipv4.conf.{iface}.arp_ignore={arp_ignore}",
            )
            success = success and retval == 0
            retval, _ = await utils.exec_command(
                "sysctl", "-q", "-w",
                f"net.ipv4.conf.{iface}.arp_announce={arp_announce}",
            )
            success = success and retval == 0
        return success

    async def _clear_dual_lan_policy_routing(self):
        retval, rules = await utils.exec_command("ip", "-4", "rule", "show")
        owned_priorities = {
            str(self.LAN1_RULE_PRIORITY),
            str(self.LAN2_RULE_PRIORITY),
        }
        rule_priorities = {
            line.split(":", 1)[0].strip()
            for line in rules.splitlines()
            if ":" in line
        } if retval == 0 else set()
        if owned_priorities.isdisjoint(rule_priorities):
            self._dual_lan_policy_initialized = False
            return

        await self._remove_dual_lan_policy_routing()

    async def _remove_dual_lan_policy_routing(self):
        for table, priority in (
            (self.LAN1_ROUTE_TABLE, self.LAN1_RULE_PRIORITY),
            (self.LAN2_ROUTE_TABLE, self.LAN2_RULE_PRIORITY),
        ):
            await utils.exec_command(
                "ip", "-4", "rule", "del", "priority", str(priority)
            )
            await utils.exec_command(
                "ip", "-4", "route", "flush", "table", str(table)
            )
        await self._set_dual_lan_arp_settings(False)
        self._dual_lan_policy_initialized = False

    async def _apply_dual_lan_policy_routing(self, active_connections):
        """Keep replies on the LAN interface that owns their source address.

        Linux otherwise chooses only the lowest-metric route when both LAN
        interfaces use the same subnet. That sends LAN2 replies through LAN1
        and also causes ARP replies for one interface to leak onto the other.
        """
        success = await self._set_dual_lan_arp_settings(True)

        for iface, connection, table, priority in (
            (
                self.LAN1_IFACE,
                self.LAN1_CONN,
                self.LAN1_ROUTE_TABLE,
                self.LAN1_RULE_PRIORITY,
            ),
            (
                self.LAN2_IFACE,
                self.LAN2_CONN,
                self.LAN2_ROUTE_TABLE,
                self.LAN2_RULE_PRIORITY,
            ),
        ):
            await utils.exec_command(
                "ip", "-4", "rule", "del", "priority", str(priority)
            )
            await utils.exec_command(
                "ip", "-4", "route", "flush", "table", str(table)
            )

            if active_connections.get(connection) != iface:
                continue

            ip, mask, gateway = await self._read_ip_from_if(iface)
            if ip is None or mask is None:
                logger.warning(
                    "Can not configure source routing for %s: no IPv4 address",
                    iface,
                )
                success = False
                continue

            network = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            retval, output = await utils.exec_command(
                "ip", "-4", "route", "add", "table", str(table),
                str(network), "dev", iface, "src", ip,
            )
            if retval != 0:
                logger.warning(
                    "Can not configure route table %s for %s: %s",
                    table,
                    iface,
                    output.strip(),
                )
                success = False

            if gateway:
                retval, output = await utils.exec_command(
                    "ip", "-4", "route", "add", "table", str(table),
                    "default", "via", gateway, "dev", iface,
                )
                if retval != 0:
                    logger.warning(
                        "Can not configure default route table %s for %s: %s",
                        table,
                        iface,
                        output.strip(),
                    )
                    success = False

            retval, output = await utils.exec_command(
                "ip", "-4", "rule", "add", "priority", str(priority),
                "from", f"{ip}/32", "table", str(table),
            )
            if retval != 0:
                logger.warning(
                    "Can not configure routing rule for %s: %s",
                    iface,
                    output.strip(),
                )
                success = False

        if not success:
            await self._remove_dual_lan_policy_routing()
            return False

        self._dual_lan_policy_initialized = success
        return success

    async def _dual_lan_policy_is_current(self, active_connections):
        retval, rules = await utils.exec_command("ip", "-4", "rule", "show")
        if retval != 0:
            return False

        for iface, connection, table, priority in (
            (
                self.LAN1_IFACE,
                self.LAN1_CONN,
                self.LAN1_ROUTE_TABLE,
                self.LAN1_RULE_PRIORITY,
            ),
            (
                self.LAN2_IFACE,
                self.LAN2_CONN,
                self.LAN2_ROUTE_TABLE,
                self.LAN2_RULE_PRIORITY,
            ),
        ):
            if active_connections.get(connection) != iface:
                if any(
                    line.split(":", 1)[0].strip() == str(priority)
                    for line in rules.splitlines()
                    if ":" in line
                ):
                    return False
                continue

            ip, mask, gateway = await self._read_ip_from_if(iface)
            if ip is None or mask is None:
                return False
            expected_rule_tokens = {
                str(priority),
                "from",
                ip,
                "lookup",
                str(table),
            }
            if not any(
                expected_rule_tokens.issubset(
                    set(line.replace(":", " ").split())
                )
                for line in rules.splitlines()
            ):
                return False

            network = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            retval, routes = await utils.exec_command(
                "ip", "-4", "route", "show", "table", str(table)
            )
            if retval != 0:
                return False
            route_tokens = {
                str(network),
                "dev",
                iface,
                "src",
                ip,
            }
            if not route_tokens.issubset(set(routes.split())):
                return False
            if gateway:
                default_tokens = {
                    "default",
                    "via",
                    gateway,
                    "dev",
                    iface,
                }
                if not default_tokens.issubset(set(routes.split())):
                    return False

        return True

    async def _restore_missing_single_ethernet_profile(self, saved_config):
        dhcp = saved_config.get("dhcp")
        if dhcp is None:
            dhcp = saved_config.get("type") == NetworkType.ETH_DHCP
        dhcp = bool(dhcp)
        self.type = NetworkType.ETH_DHCP if dhcp else NetworkType.ETH_STATIC
        self.eth_interface = saved_config.get("eth_interface") or ""

        if not dhcp:
            self.ip = saved_config.get("ip") or self.ip
            self.mask = saved_config.get("subnet_mask") or self.mask
            self.gateway = saved_config.get("gateway_ip") or ""
            dns = (saved_config.get("dns") or "").split(",")
            self.dns1 = dns[0].strip() if dns else ""
            self.dns2 = dns[1].strip() if len(dns) > 1 else ""
            try:
                ipaddress.IPv4Interface(f"{self.ip}/{self.mask}")
            except (
                ipaddress.AddressValueError,
                ipaddress.NetmaskValueError,
            ) as exc:
                logger.error(
                    "Can not restore missing Single-LAN profile: %s",
                    exc,
                )
                return False

        if not await self._add_ethernet_connection():
            return False
        return await self._activate_ethernet_connection()

    async def repair_ethernet_activation(self):
        if os.path.exists(NETWORK_APPLY_LOCK_FILE):
            logger.info("Network apply in progress; skipping ethernet repair")
            return

        saved_config = self._load_saved_network_config()
        saved_mode = self._get_saved_network_mode(saved_config)
        if saved_mode == self.NW_WIFI_ONLY:
            self._dual_lan_policy_initialized = False
            logger.info(
                "WiFi-only configuration detected; skipping Ethernet repair"
            )
            return

        if saved_mode in (self.NW_SINGLE_LAN, self.NW_LAN_WIFI):
            # The persisted mode is authoritative after a mode transition.
            # Ignore any stale dual-LAN profile that NetworkManager failed to
            # delete so it cannot reactivate policy routing in a non-dual mode.
            dual_lan_configured = False
        else:
            dual_lan_configured = await self._is_dual_lan_configured()
        if not dual_lan_configured and saved_mode == self.NW_DUAL_LAN:
            await self._restore_missing_dual_lan_profiles((False, False))
            dual_lan_configured = await self._is_dual_lan_configured()

        if dual_lan_configured:
            linked_ifaces = await self._get_linked_eth_interfaces()
            active_connections = await self._get_active_connections()
            activation_changed = False
            for iface, connection in (
                (self.LAN1_IFACE, self.LAN1_CONN),
                (self.LAN2_IFACE, self.LAN2_CONN),
            ):
                active_iface = active_connections.get(connection)
                if iface in linked_ifaces:
                    if active_iface == iface:
                        continue
                    await utils.shell(
                        f"nmcli -w 10 con up '{connection}' ifname '{iface}' || true"
                    )
                    activation_changed = True
                elif active_iface is not None:
                    await utils.shell(f"nmcli con down '{connection}' || true")
                    activation_changed = True
            if activation_changed:
                active_connections = await self._get_active_connections()
            policy_is_current = (
                self._dual_lan_policy_initialized
                and await self._dual_lan_policy_is_current(active_connections)
            )
            if activation_changed or not policy_is_current:
                await self._apply_dual_lan_policy_routing(active_connections)
            return

        self._dual_lan_policy_initialized = False
        bridge_configured = await self._single_bridge_is_configured()
        if not bridge_configured:
            wifi_exists = await self._connection_exists(self.WIFI_CONN)
            if saved_mode == self.NW_WIFI_ONLY or (
                saved_mode is None and wifi_exists
            ):
                logger.info(
                    "WiFi-only configuration detected; skipping Ethernet repair"
                )
                return
            if saved_mode in (self.NW_SINGLE_LAN, self.NW_LAN_WIFI):
                logger.warning(
                    "Single-LAN bridge missing or invalid; restoring saved configuration"
                )
                await self._delete_single_eth_connection()
                await self._restore_missing_single_ethernet_profile(saved_config)
                return
            logger.info("Ethernet profile missing; recreating default profile")
            await self.save()
            return

        active_connections = await self._get_active_connections()
        if active_connections.get(self.ETH_CONN) != self.BRIDGE_IFACE:
            logger.info("Activating Single-LAN bridge %s", self.BRIDGE_IFACE)
            await utils.shell(
                f"nmcli -w 10 con up '{self.ETH_CONN}' || true"
            )
            active_connections = await self._get_active_connections()

        linked_ifaces = await self._get_linked_eth_interfaces()
        for iface, connection in (
            (self.LAN1_IFACE, self.BRIDGE_LAN1_CONN),
            (self.LAN2_IFACE, self.BRIDGE_LAN2_CONN),
        ):
            if iface not in linked_ifaces:
                continue
            if active_connections.get(connection) == iface:
                continue
            logger.info("Activating Single-LAN bridge port %s", iface)
            await utils.shell(
                f"nmcli -w 10 con up '{connection}' ifname '{iface}' || true"
            )

    async def _add_ethernet_connection(self):
        args = [
            "nmcli", "connection", "add", "type", "bridge",
            "con-name", self.ETH_CONN, "ifname", self.BRIDGE_IFACE,
            "bridge.stp", "yes", "bridge.forward-delay", "2",
        ]
        if self.is_static():
            iface_ip = ipaddress.IPv4Interface(f"{self.ip}/{self.mask}")
            dns_value = self.dns1
            if self.dns2:
                dns_value = f"{self.dns1},{self.dns2}"
            args.extend(["ip4", str(iface_ip)])
            if self.gateway:
                args.extend(["gw4", self.gateway])
            if dns_value:
                args.extend(["ipv4.dns", dns_value])
        else:
            args.extend(["ipv4.method", "auto"])
        args.extend([
            "connection.autoconnect", "yes",
            "connection.autoconnect-retries", "0",
            "connection.autoconnect-slaves", "1",
        ])
        retval, output = await utils.exec_command(*args)
        if retval != 0:
            logger.warning("Can not create Single-LAN bridge: %s", output.strip())
            return False

        success = True
        for iface, connection in (
            (self.LAN1_IFACE, self.BRIDGE_LAN1_CONN),
            (self.LAN2_IFACE, self.BRIDGE_LAN2_CONN),
        ):
            retval, output = await utils.exec_command(
                "nmcli", "connection", "add", "type", "ethernet",
                "con-name", connection, "ifname", iface,
                "master", self.BRIDGE_IFACE, "slave-type", "bridge",
                "connection.autoconnect", "yes",
                "connection.autoconnect-retries", "0",
            )
            if retval != 0:
                logger.warning(
                    "Can not add %s to Single-LAN bridge: %s",
                    iface,
                    output.strip(),
                )
                success = False
        return success

    async def _activate_ethernet_connection(self):
        retval, output = await utils.exec_command(
            "nmcli", "-w", "10", "con", "up", self.ETH_CONN
        )
        success = retval == 0
        if retval != 0:
            logger.warning("Can not activate Single-LAN bridge: %s", output.strip())

        for connection in (self.BRIDGE_LAN1_CONN, self.BRIDGE_LAN2_CONN):
            retval, output = await utils.exec_command(
                "nmcli", "-w", "10", "con", "up", connection
            )
            if retval != 0:
                logger.info(
                    "Single-LAN bridge port %s is waiting for link: %s",
                    connection,
                    output.strip(),
                )
            success = success or retval == 0
        return success

    async def _add_wifi_connection(self, route_metric=None, force_dhcp=False):
        if self.ssid is None or self.ssid == "":
            logger.warning("WiFi SSID is empty; skipping WiFi profile creation")
            return

        route_metric_args = []
        if route_metric is not None:
            route_metric_args = [
                "ipv4.route-metric", str(route_metric),
                "ipv6.route-metric", str(route_metric),
            ]

        if self.is_static() and not force_dhcp:
            iface_ip = ipaddress.IPv4Interface(f"{self.ip}/{self.mask}")
            dns_value = self.dns1
            if self.dns2:
                dns_value = f"{self.dns1},{self.dns2}"
            args = [
                "nmcli", "connection", "add", "type", "wifi",
                "ifname", "*", "con-name", self.WIFI_CONN,
                "ssid", self.ssid, "ip4", str(iface_ip),
            ]
            if self.gateway:
                args.extend(["gw4", self.gateway])
            if dns_value:
                args.extend(["ipv4.dns", dns_value])
            args.extend([
                "802-11-wireless-security.key-mgmt", "wpa-psk",
                "802-11-wireless-security.psk", self.psk,
                "connection.autoconnect", "yes",
            ])
            args.extend(route_metric_args)
            await utils.exec_command(*args)
        else:
            await utils.exec_command(
                "nmcli", "connection", "add", "type", "wifi",
                "ifname", "*", "con-name", self.WIFI_CONN,
                "ssid", self.ssid,
                "802-11-wireless-security.key-mgmt", "wpa-psk",
                "802-11-wireless-security.psk", self.psk,
                "connection.autoconnect", "yes",
                *route_metric_args,
            )

    async def _activate_wifi_connection(self):
        if self.ssid is None or self.ssid == "":
            return
        retval, output = await utils.exec_command(
            "nmcli", "-w", "10", "con", "up", self.WIFI_CONN
        )

    async def get_current_ip(self):
        if await self._is_dual_lan_configured():
            method = await self._get_connection_ipv4_method(self.LAN1_CONN)
            self.type = (
                NetworkType.ETH_DHCP
                if method == "auto"
                else NetworkType.ETH_STATIC
            )
            self.nw_mode = self.NW_DUAL_LAN
            lan1_ip, lan1_mask, lan1_gateway = await self._read_ip_from_if(
                self.LAN1_IFACE
            )
            lan2_ip, lan2_mask, lan2_gateway = await self._read_ip_from_if(
                self.LAN2_IFACE
            )
            self.lan1_ip = lan1_ip or self.lan1_ip
            self.lan1_gateway = lan1_gateway or ""
            self.lan2_ip = lan2_ip or self.lan2_ip
            self.lan2_gateway = lan2_gateway or ""
            self.ip = self.lan1_ip or self.lan2_ip or self.ip
            self.mask = lan1_mask or lan2_mask or self.mask
            self.gateway = lan1_gateway or lan2_gateway or self.gateway
            self.eth_interface = (
                self.LAN1_IFACE if lan1_ip else
                self.LAN2_IFACE if lan2_ip else
                self.LAN1_IFACE
            )
            return

        retval, output = await utils.shell(f"nmcli -t con show {self.ETH_CONN}")
        if retval == 0: # Static ethernet is configured
            method = await self._get_connection_ipv4_method(self.ETH_CONN)
            self.type = (
                NetworkType.ETH_DHCP
                if method == "auto"
                else NetworkType.ETH_STATIC
            )
            retval, output = await utils.shell(f"nmcli -t -f GENERAL.STATE con show {self.ETH_CONN}")
            if "activated" in output:
                if await self._get_ip_from_if(self.BRIDGE_IFACE):
                    linked_ifaces = await self._get_linked_eth_interfaces()
                    self.eth_interface = linked_ifaces[0] if linked_ifaces else ""
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
        if await self._is_dual_lan_configured():
            method = await self._get_connection_ipv4_method(self.LAN1_CONN)
            self.type = (
                NetworkType.ETH_DHCP
                if method == "auto"
                else NetworkType.ETH_STATIC
            )
            return
        retval, output = await utils.shell(f"nmcli -t con show {self.ETH_CONN}")
        if retval == 0:
            retval, output = await utils.shell(f"nmcli -t -f ipv4.method c show {self.ETH_CONN}")
            if "manual" in output:
                self.type = NetworkType.ETH_STATIC
            elif "auto" in output:
                self.type = NetworkType.ETH_DHCP

    async def set_wifi(self):
        logger.info("Set WiFi")
        await self._clear_dual_lan_policy_routing()
        await self._delete_single_eth_connection()
        await self._delete_dual_lan_connections()
        await self._delete_wifi_connection()
        await self._add_wifi_connection()
        await self._activate_wifi_connection()

    async def set_ethernet(self):
        logger.info(
            "Set Single-LAN bridge across %s and %s",
            self.LAN1_IFACE,
            self.LAN2_IFACE,
        )
        await self._clear_dual_lan_policy_routing()
        await self._delete_single_eth_connection()
        await self._delete_dual_lan_connections()
        await self._delete_wifi_connection()
        await self._add_ethernet_connection()
        await self._activate_ethernet_connection()

    async def set_lan_wifi(self):
        logger.info("Set LAN + WiFi on interface %s and SSID %s", self.eth_interface, self.ssid)
        await self._clear_dual_lan_policy_routing()
        await self._delete_single_eth_connection()
        await self._delete_dual_lan_connections()
        await self._delete_wifi_connection()
        await self._add_ethernet_connection()
        await self._add_wifi_connection(route_metric=600, force_dhcp=True)

        await self._activate_ethernet_connection()
        await self._activate_wifi_connection()

    async def _add_dual_lan_connection(
        self,
        connection,
        iface,
        ip,
        gateway,
        route_metric,
    ):
        args = [
            "nmcli", "connection", "add", "type", "ethernet",
            "con-name", connection, "ifname", iface,
        ]
        if self.is_static():
            iface_ip = ipaddress.IPv4Interface(f"{ip}/{self.mask}")
            args.extend(["ip4", str(iface_ip)])
            if gateway:
                args.extend(["gw4", gateway])
            dns_value = self.dns1
            if self.dns2:
                dns_value = f"{self.dns1},{self.dns2}"
            if dns_value:
                args.extend(["ipv4.dns", dns_value])
        else:
            args.extend(["ipv4.method", "auto"])
        args.extend([
            "ipv4.route-metric", str(route_metric),
            "connection.autoconnect", "yes",
            "connection.autoconnect-retries", "0",
        ])
        retval, output = await utils.exec_command(*args)
        if retval != 0:
            logger.warning(
                "Can not create %s on %s: %s",
                connection,
                iface,
                output.strip(),
            )
        return retval == 0

    async def _restore_missing_dual_lan_profiles(self, profile_state):
        saved = self._load_saved_network_config()
        existing_connection = (
            self.LAN1_CONN if profile_state[0] else self.LAN2_CONN
        )
        existing_method = await self._get_connection_ipv4_method(
            existing_connection
        )
        dhcp = saved.get("dhcp")
        if dhcp is None:
            dhcp = existing_method == "auto"
        self.type = (
            NetworkType.ETH_DHCP
            if dhcp
            else NetworkType.ETH_STATIC
        )
        self.mask = saved.get("subnet_mask") or self.mask
        self.gateway = saved.get("gateway_ip") or ""
        self.lan1_gateway = (
            saved.get("lan1_gateway")
            if "lan1_gateway" in saved
            else self.gateway
        ) or ""
        self.lan2_gateway = saved.get("lan2_gateway") or ""
        dns = (saved.get("dns") or "").split(",")
        self.dns1 = dns[0].strip() if dns else ""
        self.dns2 = dns[1].strip() if len(dns) > 1 else ""
        self.lan1_ip = saved.get("lan1_ip") or self.lan1_ip
        self.lan2_ip = saved.get("lan2_ip") or self.lan2_ip

        try:
            ipaddress.IPv4Interface(f"{self.lan1_ip}/{self.mask}")
            ipaddress.IPv4Interface(f"{self.lan2_ip}/{self.mask}")
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc:
            logger.error("Can not restore incomplete dual-LAN profiles: %s", exc)
            return False

        restored = True
        preferred_iface = saved.get("eth_interface")
        if preferred_iface not in (self.LAN1_IFACE, self.LAN2_IFACE):
            preferred_iface = self.LAN1_IFACE

        if not profile_state[0]:
            restored = await self._add_dual_lan_connection(
                self.LAN1_CONN,
                self.LAN1_IFACE,
                self.lan1_ip,
                self.lan1_gateway,
                100 if preferred_iface == self.LAN1_IFACE else 200,
            ) and restored
        if not profile_state[1]:
            restored = await self._add_dual_lan_connection(
                self.LAN2_CONN,
                self.LAN2_IFACE,
                self.lan2_ip,
                self.lan2_gateway,
                100 if preferred_iface == self.LAN2_IFACE else 200,
            ) and restored
        return restored

    async def set_dual_lan(self):
        logger.info(
            "Set Dual LAN: LAN1(%s)=%s LAN2(%s)=%s",
            self.LAN1_IFACE,
            self.lan1_ip,
            self.LAN2_IFACE,
            self.lan2_ip,
        )
        await self._disable_auto_wired_connections()
        await self._delete_single_eth_connection()
        await utils.shell(f"nmcli con del '{self.LAN1_CONN}' || true")
        await utils.shell(f"nmcli con del '{self.LAN2_CONN}' || true")
        await self._delete_wifi_connection()

        self.mask = self.mask or "255.255.255.0"
        self.lan1_ip = self.lan1_ip or "192.168.1.100"
        self.lan2_ip = self.lan2_ip or "192.168.1.200"
        preferred_iface = (
            self.eth_interface
            if self.eth_interface in (self.LAN1_IFACE, self.LAN2_IFACE)
            else self.LAN1_IFACE
        )
        await self._add_dual_lan_connection(
            self.LAN1_CONN,
            self.LAN1_IFACE,
            self.lan1_ip,
            self.lan1_gateway,
            100 if preferred_iface == self.LAN1_IFACE else 200,
        )
        await self._add_dual_lan_connection(
            self.LAN2_CONN,
            self.LAN2_IFACE,
            self.lan2_ip,
            self.lan2_gateway,
            100 if preferred_iface == self.LAN2_IFACE else 200,
        )

        linked_ifaces = await self._get_linked_eth_interfaces()
        for iface, conn in (
            (self.LAN1_IFACE, self.LAN1_CONN),
            (self.LAN2_IFACE, self.LAN2_CONN),
        ):
            if iface in linked_ifaces:
                await utils.shell(
                    f"nmcli -w 10 con up '{conn}' ifname '{iface}' || true"
                )
        active_connections = await self._get_active_connections()
        await self._apply_dual_lan_policy_routing(active_connections)

    async def save(self):
        try:
            nw_mode = int(self.nw_mode)
        except (TypeError, ValueError):
            nw_mode = self.nw_mode

        if nw_mode == self.NW_LAN_WIFI:
            await self.set_lan_wifi()
        elif self.is_ethernet() and nw_mode == self.NW_DUAL_LAN:
            await self.set_dual_lan()
        elif self.is_ethernet():
            await self.set_ethernet()
        elif self.is_wifi():
            await self.set_wifi()
        else:
            logger.error("Error saving network config")

    async def reset_nw_config(self):
        await self._delete_single_eth_connection()
        await utils.shell(f"nmcli con del '{self.LAN1_CONN}' || true")
        await utils.shell(f"nmcli con del '{self.LAN2_CONN}' || true")
        retval, output = await utils.shell(f"nmcli con del {self.WIFI_CONN}")
        if retval != 0:
            logger.warning("Can not delete WiFi connection (not exist?)")
        self.reset()
        await self.save()
