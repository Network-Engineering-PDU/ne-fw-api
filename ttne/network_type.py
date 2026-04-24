class NetworkType:
    UNCONF      = 1
    ETH_DHCP    = 2
    ETH_STATIC  = 3
    WIFI_DHCP   = 4
    WIFI_STATIC = 5

    @classmethod
    def get_interfaces(cls):
        return ["wlan0", "eth0", "eth1"]

    @classmethod
    def from_interface(cls, interface):
        if interface == "wlan0":
            return cls.WIFI_DHCP
        if interface == "eth0" or interface == "eth1":
            return cls.ETH_DHCP
        return cls.UNCONF

    @classmethod
    def get_static(cls, network_type):
        if network_type == cls.ETH_DHCP:
            return cls.ETH_STATIC
        if network_type == cls.WIFI_DHCP:
            return cls.WIFI_STATIC
        return network_type

    @classmethod
    def is_static(cls, network_type):
        return network_type == cls.ETH_STATIC or network_type == cls.WIFI_STATIC

    @classmethod
    def to_interface(cls, network_type):
        if network_type == cls.ETH_DHCP or network_type == cls.ETH_STATIC:
            return "eth0"
        if network_type == cls.WIFI_DHCP or network_type == cls.WIFI_STATIC:
            return "wlan0"
        return "unknown_if"
    
    @classmethod
    def get_available_eth_interfaces(cls):
        """Return list of available Ethernet interfaces to try"""
        return ["eth0", "eth1"]
