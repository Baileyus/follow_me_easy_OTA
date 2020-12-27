#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Author: Duke Fong <d@d-l.io>

"""\
Follow Me OTA Tool

Depends:
  pip3 install bleak pythoncrc

Args:
  --scan
  --mac MAC         # set mac address, e.g.: "f7:d8:78:cf:93:5b"

  --bl  PATH-TO-BIN
  --sd  PATH-TO-BIN
  --app PATH-TO-BIN

  --read_conf       # read Bootloader Params
  --reboot_to 0 or 1
  --reboot
"""

import re
import struct
import asyncio
from cd_args import CdArgs

SDI_UUID = "64d3fff1-d166-11ea-87d0-0242ac130003"
SDO_UUID = "64d3fff2-d166-11ea-87d0-0242ac130003"

args = CdArgs()
scan = args.get("--scan") != None
mac_addr = args.get("--mac")

reboot_to = int(args.get("--reboot_to", dft="-1"), 0)
reboot = args.get("--reboot") != None
read_conf = args.get("--read_conf") != None

bl = args.get("--bl")
sd = args.get("--sd")
app = args.get("--app")

bl_dat = b''
sd_dat = b''
app_dat = b''

if bl:
    with open(bl, 'rb') as f:
        bl_dat = f.read()
if sd:
    with open(sd, 'rb') as f:
        sd_dat = f.read()
if app:
    with open(app, 'rb') as f:
        app_dat = f.read()

if (args.get("--help", "-h") != None or not mac_addr) and not scan:
    print(__doc__)
    exit()

from bleak import BleakClient, discover
from PyCRC.CRC16 import CRC16


# Print iterations progress
def progress_bar(iteration, total, prefix = '', suffix = '', decimals = 1, length = 50, fill = '█'):
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    print('\r%s |%s| %s%% %s' % (prefix, bar, percent, suffix), end = '')
    # Print New Line on Complete
    if iteration == total:
        print()


async def write_flash(client, addr, dat, progress=False):
    crc_w = CRC16(modbus_flag=True).calculate(dat)

    ret = await send_cmd(client, b"\x0b\x2f" + struct.pack("<II", addr, len(dat)))
    if ret != b'\x60':
        print('erase flash error:', ret.hex())
        return 1

    cur = addr
    while True:
        size = min(128, len(dat)-(cur-addr))
        if size == 0:
            break
        ret = await send_cmd(client, b"\x0b\x20" + struct.pack("<I", cur) + dat[cur-addr:cur-addr+size])
        if ret[0] != 0x60:
            print(f'write data error, cur: {cur:x}, size: {size:x}', ret.hex())
            return 1
        cur += size
        if progress:
            progress_bar(cur-addr, len(dat), prefix = 'Progress:', suffix = 'Complete')

    ret = await send_cmd(client, b"\x0b\x10" + struct.pack("<II", addr, len(dat)))
    crc_r = struct.unpack("<H", ret[1:])[0]
    if ret[0] != 0x60 or crc_w != crc_r:
        print(f'crc error, crc_w: {crc_w:x}, crc_r: {crc_r:x}, len: {len(dat):x} ret:', ret.hex())
        return 1

    return 0

recv_q = asyncio.Queue()

def callback(sender, data):
    #print(f'-> {data.hex()}')
    recv_q.put_nowait(bytes(data))

async def send_cmd(client, cmd):
    await client.write_gatt_char(SDI_UUID, bytearray(cmd))
    try:
        return await asyncio.wait_for(recv_q.get(), timeout=5)
    except asyncio.TimeoutError:
        print("send_cmd timeout, cmd:", cmd)
        return b''

async def run(loop):
    if scan:
        print("scan...")
        devices = await discover()
        print("results:")
        for d in devices:
            print(d)
        return

    print(f"connect to {mac_addr}");
    async with BleakClient(mac_addr, loop=loop) as client:
        await client.start_notify(SDO_UUID, callback)
        print("notify subscribed");
        print("read version:", (await send_cmd(client, b"\x01\x01")).hex());

        if read_conf:
            conf = await send_cmd(client, b"\x0b\x00" + struct.pack("<IB", 0x7e000, 16))
            print(f"read conf {conf[0]:x}: {conf[1:].hex()}");
            return

        if sd or bl:
            if sd:
                print("write sd:")
                ret = await write_flash(client, 0x40000, sd_dat, True)
                if ret:
                    return

            if bl:
                print("write bl:")
                ret = await write_flash(client, 0x65000, bl_dat, True)
                if ret:
                    return

            print("write conf")
            ret = await write_flash(client, 0x7e000, struct.pack("<IIII", 0xcdcd0001, len(bl_dat), len(sd_dat), 0))
            if ret:
                return

        elif app:
            print("write app:")
            ret = await write_flash(client, 0x40000, app_dat, True)
            if ret:
                return

            print("write conf")
            ret = await write_flash(client, 0x7e000, struct.pack("<IIII", 0xcdcd0001, 0, 0, len(app_dat)))
            if ret:
                return

        if reboot_to != -1:
            print(f"reboot to {reboot_to}:", (await send_cmd(client, b"\x0a\x22" + struct.pack("<B", reboot_to))).hex())
            return

        if reboot:
            print(f"reboot:", (await send_cmd(client, b"\x0a\x20")).hex())
            return

        print("write done")

loop = asyncio.get_event_loop()
loop.run_until_complete(run(loop))

