"""Synchronous motion transport backed by one persistent Bleak event loop."""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import queue
import math
import threading

from ..protocol import format_wire
from .base import Transport

SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


class BluetoothTransport(Transport):
    """BLE UART for Pico W. Only ASCII control commands cross this link.

    A dedicated loop keeps Bleak connections alive between synchronous calls,
    including when the caller already runs an asyncio loop. Writes are ordered,
    bounded, and acknowledged by GATT; a lost link raises instead of replaying
    potentially stale motion commands.
    """

    def __init__(self, name="PicoRobot", address="", timeout=10.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Bluetooth timeout must be finite and positive")
        if not name and not address:
            raise ValueError("Set a Bluetooth name or address")
        self.name, self.address, self.timeout = name, address, timeout
        self._loop = None
        self._thread = None
        self._client = None
        self._lock = threading.RLock()
        self._replies = queue.Queue(maxsize=64)
        self._rx = bytearray()

    def _run(self, coroutine):
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(self.timeout * 2 + 2)
        except FutureTimeout:
            future.cancel()
            raise TimeoutError("Pico Bluetooth operation timed out") from None

    async def _connect(self):
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:
            raise ImportError("Install Bluetooth support: python -m pip install bleak") from exc
        if self.address:
            device = await BleakScanner.find_device_by_address(
                self.address, timeout=self.timeout)
        else:
            device = await BleakScanner.find_device_by_filter(
                lambda device, adv: adv.local_name == self.name,
                timeout=self.timeout)
        if device is None:
            raise ConnectionError(f"Pico BLE device {self.address or self.name!r} not found")
        self._client = BleakClient(device, timeout=self.timeout)
        await self._client.connect()
        missing = [uuid for uuid in (RX_UUID, TX_UUID)
                   if self._client.services.get_characteristic(uuid) is None]
        if missing:
            available = [char.uuid for service in self._client.services
                         for char in service.characteristics]
            raise ConnectionError(
                "Device found and connected, but its firmware uses a different BLE protocol. "
                f"Missing UART characteristics: {', '.join(missing)}. "
                f"Available characteristics: {', '.join(available) or '(none)'}. "
                "Ask for the firmware's write/notify UUIDs and packet format.")
        await self._client.start_notify(TX_UUID, self._notify)

    def _notify(self, _sender, data):
        self._rx.extend(data)
        while b"\n" in self._rx:
            line, _, rest = self._rx.partition(b"\n")
            self._rx = bytearray(rest)
            try:
                self._replies.put_nowait(line.decode("ascii", errors="replace").strip())
            except queue.Full:
                pass
        if len(self._rx) > 256:
            self._rx.clear()

    def open(self):
        with self._lock:
            if self.is_open():
                return
            self.close()
            self._rx.clear()
            while not self._replies.empty():
                self._replies.get_nowait()
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._thread.start()
            try:
                self._run(self._connect())
            except BaseException:
                self.close()
                raise

    async def _disconnect(self):
        if self._client is not None:
            await self._client.disconnect()

    async def _cancel_pending(self):
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def close(self):
        with self._lock:
            if self._loop is None:
                return
            try:
                self._run(self._disconnect())
            finally:
                self._run(self._cancel_pending())
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join()
                self._loop.close()
                self._loop = self._thread = self._client = None

    def is_open(self):
        return self._client is not None and self._client.is_connected

    async def _write(self, payload):
        # 20-byte chunks also work with the minimum ATT MTU of 23.
        for offset in range(0, len(payload), 20):
            await self._client.write_gatt_char(RX_UUID, payload[offset:offset + 20], response=True)

    def send_line(self, line):
        payload = format_wire(line)
        if len(payload) > 96 or b"\n" in payload[:-1] or b"\r" in payload[:-1]:
            raise ValueError("Expected one robot command of at most 95 ASCII characters")
        with self._lock:
            if not self.is_open():
                raise ConnectionError("Pico Bluetooth connection is closed; reconnect before sending motion")
            try:
                self._run(self._write(payload))
            except Exception:
                self.close()
                raise

    def recv_line(self, timeout=None):
        try:
            return self._replies.get(timeout=self.timeout if timeout is None else timeout)
        except queue.Empty:
            return None
