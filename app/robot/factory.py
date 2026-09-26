"""Build a RobotController from env / CLI transport settings."""
from __future__ import annotations

from .config import RobotHardwareConfig
from .controller import RobotController
from .transport.bluetooth import BluetoothTransport
from .transport.mock import MockTransport
from .transport.serial_transport import SerialTransport
from .transport.wifi import WifiTransport


def connect_robot(
    config: RobotHardwareConfig | None = None,
    *,
    transport: str | None = None,
    bluetooth_name: str | None = None,
    bluetooth_address: str | None = None,
    wifi_host: str | None = None,
    wifi_port: int | None = None,
    serial_port: str | None = None,
    mock: bool = False,
) -> RobotController:
    """Create a live RobotController.

    Preference when transport is auto:
      1) BLE address  2) Wi-Fi host  3) USB serial  4) Pico BLE by name
    """
    cfg = config or RobotHardwareConfig.from_env()
    updates = {}
    if transport:
        updates["transport"] = transport
    if bluetooth_name is not None:
        updates["bluetooth_name"] = bluetooth_name
    if bluetooth_address is not None:
        updates["bluetooth_address"] = bluetooth_address
    if wifi_host is not None:
        updates["wifi_host"] = wifi_host
    if wifi_port is not None:
        updates["wifi_port"] = wifi_port
    if serial_port is not None:
        updates["serial_port"] = serial_port
    if mock:
        updates["transport"] = "mock"
    if updates:
        cfg = cfg.with_updates(**updates)

    mode = cfg.resolved_transport()
    if mode == "bluetooth":
        return RobotController(BluetoothTransport(
            cfg.bluetooth_name, cfg.bluetooth_address, cfg.bluetooth_timeout), cfg)
    if mode == "wifi":
        if not cfg.wifi_host:
            raise ValueError("Set ROBOT_WIFI_HOST or pass wifi_host= for Wi-Fi transport")
        link = WifiTransport(cfg.wifi_host, cfg.wifi_port, cfg.wifi_timeout)
        return RobotController(link, cfg)
    if mode == "serial":
        if not cfg.serial_port:
            raise ValueError("Set ROBOT_SERIAL_PORT or pass serial_port= for USB serial")
        link = SerialTransport(cfg.serial_port, cfg.serial_baud, cfg.serial_timeout)
        return RobotController(link, cfg)
    return RobotController(MockTransport(), cfg)
