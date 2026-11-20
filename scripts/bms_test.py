"""One-shot read of a JBD BMS: python scripts/bms_test.py <MAC>"""

import asyncio
import json
import sys

from bleak import BleakClient

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from boatdash.jbd import JBDClient, NOTIFY_UUID  # noqa: E402


async def main(address: str) -> None:
    bms = JBDClient("test", address)
    async with BleakClient(address, timeout=20) as client:
        await client.start_notify(NOTIFY_UUID, bms._on_notify)
        await bms.read_once(client)
    print(json.dumps(bms.state.to_dict(), indent=2))


asyncio.run(main(sys.argv[1]))
