"""What plugins import. See docs/CUSTOM_DEVICES.md."""
from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.extensions import Action, Peripheral, battery_reading, run_command, usb_present

__all__ = ["Action", "BatteryReading", "Peripheral", "battery_reading", "run_command", "usb_present"]
