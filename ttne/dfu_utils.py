from typing import Dict

def hex_load(hex_raw_data: str) -> Dict[int, int]:
    hex_data = {}

    address_prefix = 0
    next_address = 0
    trailing_address = 0

    for line in hex_raw_data.splitlines():
        if line[7:9] == "02":
            address_prefix = int(line[9:13], base=16) << 4

        elif line[7:9] == "04":
            address_prefix = int(line[9:13], base=16) << 16

        elif line[7:9] == "00":
            address_base = int(line[3:7], base=16)
            address = address_prefix + address_base
            # Jump in hex
            #if (next_address != address and next_address):
                #break

            line_data = bytes.fromhex(line[9:-2])
            for i in range(len(line_data)):
                hex_data[address+i] = line_data[i]
                if line_data[i] != 0xFF:
                    trailing_address = address+i
            next_address = address + len(line_data)

    key_list = list(hex_data.keys())
    for key in key_list:
        if key > trailing_address:
            del hex_data[key]

    return hex_data
