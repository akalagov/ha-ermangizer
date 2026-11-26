"""A minimal Modbus TCP device for tests: enough of the protocol to serve the
registers our layouts define and to record what the integration asked for."""
from __future__ import annotations

import asyncio
from struct import pack, unpack

READ_FUNCTIONS = {3: "holding", 4: "input"}


class FakeModbusDevice:
    def __init__(self, inputs: dict[int, int], holdings: dict[int, int]) -> None:
        self.tables = {"input": dict(inputs), "holding": dict(holdings)}
        self.coils: dict[int, bool] = {}
        self.requests: list[tuple[str, int, int]] = []
        self.writes: list[tuple] = []
        self._server: asyncio.Server | None = None
        self._writers: list = []
        self.port: int = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if not self._server:
            return
        self._server.close()
        # wait_closed() would block until every handler returns, and a handler
        # only returns once its client disconnects - which an un-loaded entry
        # never does. Drop the connections instead.
        for writer in self._writers:
            writer.close()
        self._writers.clear()

    async def _handle(self, reader: asyncio.StreamReader, writer) -> None:
        self._writers.append(writer)
        while True:
            try:
                header = await reader.readexactly(7)
                transaction, _, length, unit = unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
            except (asyncio.IncompleteReadError, ConnectionResetError):
                writer.close()
                return
            reply = self._pdu(pdu)
            # Echo the transaction id: a Modbus TCP client correlates responses
            # by it and discards anything that does not match.
            writer.write(
                pack(">HHHB", transaction, 0, len(reply) + 1, unit) + reply
            )
            await writer.drain()

    def _pdu(self, pdu: bytes) -> bytes:
        function = pdu[0]
        if function in READ_FUNCTIONS:
            start, quantity = unpack(">HH", pdu[1:5])
            table = self.tables[READ_FUNCTIONS[function]]
            self.requests.append((READ_FUNCTIONS[function], start, quantity))
            values = [table.get(start + i, 0) for i in range(quantity)]
            return bytes([function, quantity * 2]) + b"".join(
                pack(">H", v) for v in values
            )
        if function == 5:  # write single coil
            address, value = unpack(">HH", pdu[1:5])
            self.coils[address] = value == 0xFF00
            self.writes.append(("coil", address, value == 0xFF00))
            return pdu[:5]
        if function == 6:  # write single register
            address, value = unpack(">HH", pdu[1:5])
            self.tables["holding"][address] = value
            self.writes.append(("register", address, value))
            return pdu[:5]
        if function == 16:  # write multiple registers
            address, quantity = unpack(">HH", pdu[1:5])
            for i in range(quantity):
                (value,) = unpack(">H", pdu[6 + 2 * i : 8 + 2 * i])
                self.tables["holding"][address + i] = value
                self.writes.append(("register", address + i, value))
            return bytes([function]) + pdu[1:5]
        return bytes([function | 0x80, 1])  # illegal function
