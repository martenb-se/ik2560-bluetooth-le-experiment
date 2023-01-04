"""Program to test Bluetooth LE.

Supports:
 - (Automatically) connecting devices to each other.
 - Monitoring RSSI of connected devices.

Developed with help from the "Bluetooth® Technology for Linux Developers"
package found at:
https://www.bluetooth.com/bluetooth-resources/bluetooth-for-linux/
"""
from typing import Dict, Callable, Union
import argparse
import random
import re
import threading
from enum import Enum, auto
from datetime import datetime
import time
from threading import Thread, Lock
import sys
import signal

import dbus
import dbus.exceptions
import dbus.service
import dbus.mainloop.glib
from dbus.bus import BusConnection
from dbus.connection import SignalMatch
from gi.repository import GLib

from bluetooth_for_linux import bluetooth_constants, bluetooth_utils
from bluetooth_for_linux.bluetooth_advertisement import Advertisement

# ------ [ Unique Device Information ] ----------------------------------------

# Machine ID
device_id: str = "00000000"


def make_device_id(alternative: int = 0) -> str:
    """Make a device ID from the computer's machine ID, if unable then an
    ID will be generated from a predefined string.

    :param alternative: Alternative generation if there was a collision
    :return: A device ID
    """
    global device_id

    # Standard full id (will cause many collisions)
    full_id = "cf8b5eff3cf267a736e0371c55108987"

    try:
        with open("/etc/machine-ida") as f:
            full_id = f.read().splitlines()[0]
    except FileNotFoundError:
        pass

    index_from = alternative % len(full_id)
    index_to = (alternative + 8) % len(full_id)

    full_id_int = int(full_id, 16)
    full_id_multiplier = 1 + int(alternative / len(full_id))
    full_id_max = int("f" * len(full_id), 16)

    full_id_alternative = \
        hex(int(full_id_int * full_id_multiplier) % full_id_max)[2:]

    if index_to < index_from:
        return full_id_alternative[index_from:len(full_id)] + \
               full_id_alternative[0:index_to]
    else:
        device_id = full_id_alternative[index_from:index_to]


# Generate ID Once
make_device_id()

# ------ [ Settings ] ---------------------------------------------------------
# Advertisement name (max 29 bytes)
device_name: str = "BT-ScatterNode-" + device_id

# Devices to look for
device_find: str = "BT-ScatterNode-"

# Connection goal
devices_connect_to: int = 1


# ------ [ Constants ] --------------------------------------------------------


class NodeModes(Enum):
    NONE = auto()
    CENTRAL = auto()
    PERIPHERAL = auto()


class ProgramStates(Enum):
    STEP_INIT = auto()
    STEP_DISCOVERY_START = auto()
    STEP_DISCOVERY_RUNNING = auto()
    STEP_DISCOVERY_DONE = auto()
    STEP_ADVERTISING_START = auto()
    STEP_ADVERTISING_ACTIVE = auto()
    STEP_ADVERTISING_DONE = auto()
    STEP_DISCOVER_ADVERTISE_START = auto()
    STEP_DISCOVER_ADVERTISE_ACTIVE = auto()
    STEP_DISCOVER_ADVERTISE_DONE = auto()
    STEP_CONNECTION_START = auto()
    STEP_CONNECTION_ACTIVE = auto()
    STEP_CONNECTION_DONE = auto()
    STEP_KILL_PROGRAM = auto()


# ------ [ Program State ] ----------------------------------------------------
# Step in program process
current_step: ProgramStates = ProgramStates.STEP_INIT

# Have all known devices been seen
seen_all_devices: bool = False

# All found devices
devices_found: Dict[str, Dict[str, any]] = {}

# Information about found devices
devices_info: Dict[str, Dict[str, any]] = {}

# All devices already managed by BlueZ
managed_objects_found: int = 0

# Roles to other devices (central, peripheral)
role_to_device: Dict[str, NodeModes] = {}

# Connected devices
devices_connected: Dict[str, Dict[str, any]] = {}

# State reset
mainloop: Union[GLib.MainLoop, None] = None
adapter_interface: Union[dbus.Interface, None] = None
timer_id: Union[int, None] = None
adv_mgr_interface: Union[dbus.Interface, None] = None
adv: Union[Advertisement, None] = None

# Bus
glob_connection_bus: Union[BusConnection, None] = None

# Signal Receivers
signal_scan_add: Union[SignalMatch, None] = None
signal_scan_remove: Union[SignalMatch, None] = None
signal_scan_update: Union[SignalMatch, None] = None

signal_adv_add: Union[SignalMatch, None] = None
signal_adv_update: Union[SignalMatch, None] = None

# Mutexes
mutex_role_to_device: threading.Lock = Lock()


# ------ [ Methods ] ----------------------------------------------------------
# ------ [ Methods - Signal Handlers ] ----------------------------------------


def handler_signal_interrupt(sig: int, frame: any) -> None:
    """Handler for interrupt signals to shut down the program in a controlled
    manner.

    :param sig: The signal number.
    :param frame: The frame object (see,
    https://docs.python.org/3/reference/datamodel.html#frame-objects,
    https://docs.python.org/3/library/inspect.html#module-inspect)
    :return: Nothing
    """
    global current_step, devices_connected

    print("Killing program...")

    if current_step == ProgramStates.STEP_DISCOVERY_START or \
            current_step == ProgramStates.STEP_DISCOVERY_RUNNING:
        discovery_stop()

    elif current_step == ProgramStates.STEP_ADVERTISING_START or \
            current_step == ProgramStates.STEP_ADVERTISING_ACTIVE:
        advertising_stop()

    if len(devices_connected) > 0:
        connection_monitor_stop()

    current_step = ProgramStates.STEP_KILL_PROGRAM
    sys.exit(0)


# ------ [ Methods - Program Execution ] --------------------------------------


def initialize_dbus() -> BusConnection:
    """Initialize a DBus connection

    :return: The Dbus SystemBus connection instance used for communications
    """
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    return dbus.SystemBus()


def register_signal_handlers() -> None:
    """Register handlers for the following system signals:
      - Interrupts

    :return: Nothing
    """
    signal.signal(signal.SIGINT, handler_signal_interrupt)


def connect_to_devices(
        bus: BusConnection,
        devices_to_connect: Dict[str, Dict[str, any]]) -> None:
    """Connect to all provided devices.

    :param bus: The DBus BusConnection used for communications.
    :param devices_to_connect: The devices to connect to.
    :return: Nothing
    """
    global devices_connected

    for path, raw_properties in devices_to_connect.items():
        device_address = devices_found[path]["Address"]

        device_proxy = \
            bus.get_object(bluetooth_constants.BLUEZ_SERVICE_NAME,
                           path)
        device_interface = \
            dbus.Interface(device_proxy,
                           bluetooth_constants.DEVICE_INTERFACE)

        device_connected = get_device_property_value(
            bus, path, "Connected")

        if device_connected is not None and \
                not device_connected:
            print_info_connect_to_device(path, device_address)
            connect(device_interface)

        else:
            print_info_already_connected_to_device(path, device_address)

        if path not in devices_connected:
            devices_connected[path] = raw_properties


def disconnect_from_all_devices() -> None:
    """Disconnect from all connected devices.

    :return: Nothing
    """
    global devices_connected, glob_connection_bus

    devices_connected_copy = devices_connected.copy()
    for path, raw_properties in devices_connected_copy.items():

        device_address = "??:??:??:??:??:??"
        if "Address" in devices_connected[path]:
            device_address = devices_connected[path]["Address"]

        device_proxy = \
            glob_connection_bus.get_object(
                bluetooth_constants.BLUEZ_SERVICE_NAME,
                path)

        device_interface = \
            dbus.Interface(device_proxy,
                           bluetooth_constants.DEVICE_INTERFACE)

        print_info_disconnect_from_device(path, device_address)
        disconnect(device_interface)
        del devices_connected[path]


# ------ [ Methods - Information ] --------------------------------------------


def get_device_info_name(device_pth: str) -> str:
    """Get device name for the device provided by its path

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :return: The name of the device along with its Bluetooth address or
    "Unknown" and its Bluetooth address if the name was not found.
    """
    found_device_name = "Unknown"
    if "Name" in devices_found[device_pth]:
        found_device_name = \
            bluetooth_utils.dbus_to_python(
                devices_found[device_pth]["Name"]) + \
            " (" + \
            bluetooth_utils.dbus_to_python(
                devices_found[device_pth]["Address"]) + \
            ")"

    elif "Address" in devices_found[device_pth]:
        found_device_name = found_device_name + " (" + \
                            bluetooth_utils.dbus_to_python(
                                devices_found[device_pth]["Address"]) + \
                            ")"

    return found_device_name


def print_info_dated_msg(*message: any) -> None:
    """Print dated information message.

    :param message: The message(s) to print.
    :return: Nothing
    """
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "-", *message)


def print_info_existing_device(device_props: Dict[str, any]) -> None:
    """Print info for existing device already managed BlueZ.

    :param device_props: The DBus properties dict for the device.
    :return: Nothing
    """
    existing_device_name = "Unknown"
    if "Name" in device_props:
        existing_device_name = \
            bluetooth_utils.dbus_to_python(device_props["Name"])
    elif "Address" in device_props:
        existing_device_name = existing_device_name + " (" + \
                               bluetooth_utils.dbus_to_python(
                                   device_props["Address"]) + \
                               ")"

    print_info_dated_msg("Existing device:", existing_device_name)


def print_info_found_device(device_pth: str) -> None:
    """Print info for found device by scanning.

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :return: Nothing
    """
    print_info_dated_msg("Found device:", get_device_info_name(device_pth))


def print_info_removed_device(device_pth: str) -> None:
    """Print info for a device that was removed by BlueZ.

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :return: Nothing
    """
    print_info_dated_msg(
        "Removed inactive device:", get_device_info_name(device_pth))


def print_info_updated_device(
        device_pth: str, changed: Dict[str, any]) -> None:
    """Print info for a device that was removed by BlueZ.

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :param changed: The device properties that changed.
    :return: Nothing
    """
    print_info_dated_msg(
        "Updated info for device:", get_device_info_name(device_pth),
        f"({len(bluetooth_utils.dbus_to_python(changed))} change(s))")


def print_info_seen_device(device_pth: str, rssi: int) -> None:
    """Print info for a device that was seen as active by BlueZ.

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :param rssi: The RSSI for the seen device.
    :return: Nothing
    """
    print_info_dated_msg(
        "Device is active and seen:", get_device_info_name(device_pth),
        "(RSSI:", rssi, ")")


def print_info_not_seen_device(device_pth: str) -> None:
    """Print info for a device that was seen as active by BlueZ.

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :return: Nothing
    """
    print_info_dated_msg(
        "Device is no longer seen:", get_device_info_name(device_pth))


def print_info_connect_to_device(
        device_pth: str, device_addr: str) -> None:
    """Print info for connecting to a device.

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :param device_addr: The Bluetooth address to the device.
    :return: Nothing
    """
    print_info_dated_msg(
        "Connecting to device:", get_device_info_name(device_pth),
        "(", device_addr, ")")


def print_info_already_connected_to_device(
        device_pth: str, device_addr: str) -> None:
    """Print info for device that is already connected to.

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :param device_addr: The Bluetooth address to the device.
    :return: Nothing
    """
    print_info_dated_msg(
        "Already connected to device:", get_device_info_name(device_pth),
        "(", device_addr, ")")


def print_info_disconnect_from_device(
        device_pth: str, device_addr: str) -> None:
    """Print info for disconnecting from a device.

    :param device_pth: The DBus ObjectPath to the device to print info for.
    :param device_addr: The Bluetooth address to the device.
    :return: Nothing
    """
    print_info_dated_msg(
        "Disconnected from device:", get_device_info_name(device_pth),
        "(", device_addr, ")")


# ------ [ Methods - Basics ] -------------------------------------------------


def is_device_matching(device_properties: Dict[str, any]) -> bool:
    """Check if provided device match against the well known name.

    :param device_properties: The DBus properties dict of the device to
    match to.
    :return: Returns True if the properties match against the known devices.
    """
    global device_find
    return "Name" in device_properties and \
           re.search(r"^" + re.escape(device_find) + r"[a-f\d]{8}$",
                     bluetooth_utils.dbus_to_python(
                         device_properties["Name"]))


def get_matching_and_active_devices() -> Dict[str, Dict[str, any]]:
    """Get all matching and active devices.

    :return: A DBus dict of all matching devices.
    """
    global devices_found

    matching_and_active_dev = {}
    for path, device_props in devices_found.items():
        is_seen = False
        if path in devices_info and "seen" in devices_info[path]:
            is_seen = devices_info[path]["seen"]

        if is_seen and is_device_matching(device_props):
            matching_and_active_dev[path] = device_props

    return matching_and_active_dev


# ------ [ Methods - Thread ] -------------------------------------------------


def thread_check_seen_devices(bus: BusConnection) -> None:
    """Thread to continuously check for seen devices.

    :param bus: The DBus BusConnection used for communications.
    :return: Nothing
    """
    global current_step, seen_all_devices

    while current_step != ProgramStates.STEP_KILL_PROGRAM \
            and current_step != ProgramStates.STEP_DISCOVERY_DONE:
        might_have_seen_all_devices = True
        if current_step == ProgramStates.STEP_DISCOVERY_RUNNING:
            devices_found_copy = devices_found.copy()
            for path, raw_data in devices_found_copy.items():
                if path not in devices_info or \
                        "seen" not in devices_info[path]:
                    devices_info[path] = {"seen": False}
                elif devices_info[path]["seen"]:
                    continue

                device_rssi: int = \
                    get_device_property_value(bus, path, "RSSI")

                if device_rssi is not None:
                    devices_info[path]["seen"] = True
                    print_info_seen_device(path, device_rssi)

                else:
                    if devices_info[path]["seen"] is not False:
                        devices_info[path]["seen"] = False
                        print_info_not_seen_device(path)

                    might_have_seen_all_devices = False

            if might_have_seen_all_devices:
                seen_all_devices = True

        time.sleep(2)


def thread_timeout_advertisement(timeout: int) -> None:
    """Timeout for sending advertisements.

    :param timeout: The timeout in seconds.
    :return: Nothing
    """
    global current_step, devices_connected, devices_connect_to

    for sleep_timer in range(timeout):
        if len(devices_connected) >= devices_connect_to:
            print("Reached connection goal!")
            break

        if current_step == ProgramStates.STEP_KILL_PROGRAM:
            return

        time.sleep(1)

    if current_step == ProgramStates.STEP_ADVERTISING_START or \
            current_step == ProgramStates.STEP_ADVERTISING_ACTIVE:
        advertising_stop()
        current_step = ProgramStates.STEP_DISCOVERY_DONE


def thread_timeout_discover_and_advertise(timeout: int) -> None:
    """Timeout for the "discover and advertise" process.

    :param timeout: The timeout in seconds.
    :return: Nothing
    """
    global current_step

    for sleep_timer in range(timeout):
        if current_step == ProgramStates.STEP_KILL_PROGRAM:
            return

        if current_step != ProgramStates.STEP_DISCOVER_ADVERTISE_START and \
                current_step != ProgramStates.STEP_DISCOVER_ADVERTISE_ACTIVE:
            break

        time.sleep(1)

    if current_step == ProgramStates.STEP_DISCOVER_ADVERTISE_START or \
            current_step == ProgramStates.STEP_DISCOVER_ADVERTISE_ACTIVE:
        discover_and_advertise_stop()
        current_step = ProgramStates.STEP_DISCOVER_ADVERTISE_DONE


def thread_connect_discover_and_advertise() -> None:
    """Connect to matching devices during "discover and advertise" process.

    :return: Nothing
    """
    global current_step, glob_connection_bus, devices_found

    while current_step != ProgramStates.STEP_KILL_PROGRAM and \
            (current_step == ProgramStates.STEP_DISCOVER_ADVERTISE_START or
             current_step == ProgramStates.STEP_DISCOVER_ADVERTISE_ACTIVE):
        time.sleep(random.randint(5, 10))

        if current_step == ProgramStates.STEP_KILL_PROGRAM:
            return

        devices_found_copy = devices_found.copy()
        for path, raw_data in devices_found_copy.items():
            if is_device_matching(raw_data):
                dev_name = "Unknown"
                if "Name" in raw_data:
                    dev_name = \
                        bluetooth_utils.dbus_to_python(raw_data["Name"])
                dev_address = "??:??:??:??:??:??"
                if "Address" in raw_data:
                    dev_address = \
                        bluetooth_utils.dbus_to_python(raw_data["Address"])

                mutex_role_to_device.acquire()
                if path not in role_to_device or \
                        role_to_device[path] == NodeModes.NONE:
                    print(f"Connect to {dev_name} ({dev_address})..")
                    try:
                        connect_to_devices(glob_connection_bus,
                                           {path: raw_data})
                        role_to_device[path] = NodeModes.CENTRAL

                    except Exception as e:
                        print("Failed to connect", e)
                mutex_role_to_device.release()

        print_info_dated_msg(
            "Total connected devices:", len(devices_connected))

        if len(devices_connected) >= devices_connect_to:
            print("Reached device goal!")
            discover_and_advertise_stop()
            return


def thread_check_connected_devices(bus: BusConnection) -> None:
    """Check for connected devices.

    :param bus: The DBus BusConnection used for communications.
    :return: Nothing
    """
    global current_step

    while current_step != ProgramStates.STEP_KILL_PROGRAM and \
            current_step == ProgramStates.STEP_CONNECTION_START or \
            current_step == ProgramStates.STEP_CONNECTION_ACTIVE:
        devices_found_copy = devices_connected.copy()

        if len(devices_found_copy) == 0:
            print_info_dated_msg("No connected devices...")

        for path, raw_properties in devices_found_copy.items():
            name = "Unknown"
            prop_name = get_device_property_value(bus, path, "Name")
            if "Name" in raw_properties:
                name = \
                    bluetooth_utils.dbus_to_python(
                        raw_properties["Name"]) + \
                    " (" + \
                    bluetooth_utils.dbus_to_python(
                        raw_properties["Address"]) + \
                    ")"

            elif prop_name is not None:
                name = \
                    prop_name + \
                    " (" + \
                    bluetooth_utils.dbus_to_python(
                        raw_properties["Address"]) + \
                    ")"

            elif "Address" in raw_properties:
                name = \
                    name + " (" + \
                    bluetooth_utils.dbus_to_python(
                        raw_properties["Address"]) + \
                    ")"

            rssi = "-"
            prop_rssi = get_device_property_value(bus, path, "RSSI")
            if prop_rssi is not None:
                rssi = prop_rssi

            print_info_dated_msg(f"{name}: {rssi} dBm")

        time.sleep(5)


# ------ [ Methods - DBus & BlueZ ] -------------------------------------------


def get_device_properties_interface(
        bus: BusConnection, device_pth: str) -> dbus.Interface:
    """Get the DBus properties interface for the selected device.

    :param bus: The DBus BusConnection used for communications.
    :param device_pth: The path to the device.
    :return: The DBus properties interface with all available
    device properties.
    """
    device_object = \
        bus.get_object(bluetooth_constants.BLUEZ_SERVICE_NAME, device_pth)
    device = \
        dbus.Interface(device_object, bluetooth_constants.DEVICE_INTERFACE)
    device_properties = \
        dbus.Interface(device, bluetooth_constants.DBUS_PROPERTIES)

    return device_properties


def get_device_property_value(
        bus: BusConnection, device_pth: str,
        device_property_name: str) -> any:
    """Get the provided property value for the selected device.

    :param bus: The DBus BusConnection used for communications.
    :param device_pth: The DBus ObjectPath to the device.
    :param device_property_name: The property name to get the value for.
    :return: The value of the property if it exists, otherwise None
    """
    device_properties = get_device_properties_interface(bus, device_pth)
    try:
        property_value = \
            device_properties.Get(bluetooth_constants.DEVICE_INTERFACE,
                                  device_property_name)
        return property_value
    except dbus.exceptions.DBusException:
        return None


def find_known_devices(bus: BusConnection) -> None:
    """Get all devices already known by BlueZ and update the found devices
    accordingly.

    :param bus: The DBus BusConnection used for communications.
    :return: Nothing
    """
    global current_step, managed_objects_found

    object_manager = \
        dbus.Interface(
            bus.get_object(bluetooth_constants.BLUEZ_SERVICE_NAME, "/"),
            bluetooth_constants.DBUS_OM_IFACE)

    managed_objects = object_manager.GetManagedObjects()
    for path, ifaces in managed_objects.items():
        for iface_name in ifaces:
            if iface_name == bluetooth_constants.DEVICE_INTERFACE:
                device_properties = \
                    ifaces[bluetooth_constants.DEVICE_INTERFACE]

                print_info_existing_device(device_properties)
                managed_objects_found += 1
                devices_found[path] = device_properties


def discovery_start(bus: BusConnection, timeout: int) -> None:
    """Start device discovery to find all known devices.

    :param bus: The DBus BusConnection used for communications.
    :param timeout: Timeout for discovery process.
    :return: Nothing
    """
    global current_step, adapter_interface, mainloop, timer_id, \
        signal_scan_add, signal_scan_remove, signal_scan_update
    current_step = ProgramStates.STEP_DISCOVERY_START

    adapter_path = \
        bluetooth_constants.BLUEZ_NAMESPACE + bluetooth_constants.ADAPTER_NAME
    adapter_object = \
        bus.get_object(bluetooth_constants.BLUEZ_SERVICE_NAME, adapter_path)
    adapter_interface = \
        dbus.Interface(adapter_object, bluetooth_constants.ADAPTER_INTERFACE)

    signal_scan_add = bus.add_signal_receiver(
        handle_interface_added,
        dbus_interface=bluetooth_constants.DBUS_OM_IFACE,
        signal_name="InterfacesAdded")

    signal_scan_remove = bus.add_signal_receiver(
        handle_interface_removed,
        dbus_interface=bluetooth_constants.DBUS_OM_IFACE,
        signal_name="InterfacesRemoved")

    signal_scan_update = bus.add_signal_receiver(
        handle_properties_changed,
        dbus_interface=bluetooth_constants.DBUS_PROPERTIES,
        signal_name="PropertiesChanged",
        path_keyword="path")

    mainloop = GLib.MainLoop()

    if not timeout > 0:
        timeout = 30

    timer_id = GLib.timeout_add(timeout, discovery_stop)

    adapter_interface.StartDiscovery(byte_arrays=True)
    current_step = ProgramStates.STEP_DISCOVERY_RUNNING
    mainloop.run()


def discovery_stop() -> None:
    """Stop the discovery process and remove all event listeners.

    :return: Nothing
    """
    global current_step, adapter_interface, mainloop, timer_id, \
        signal_scan_add, signal_scan_remove, signal_scan_update

    if timer_id is not None:
        GLib.source_remove(timer_id)

    if mainloop is not None:
        mainloop.quit()

    if adapter_interface is not None:
        adapter_interface.StopDiscovery()

    if signal_scan_add is not None:
        signal_scan_add.remove()

    if signal_scan_remove is not None:
        signal_scan_remove.remove()

    if signal_scan_update is not None:
        signal_scan_update.remove()

    current_step = ProgramStates.STEP_DISCOVERY_DONE


def connect(device_inf: dbus.Interface) -> int:
    """Connect to the device using its device path.

    :param device_inf: The DBus interfaces for the device.
    :return: Status code
    """
    try:
        device_inf.Connect()
    except dbus.exceptions.DBusException as e:
        print("Failed to connect")
        print(e.get_dbus_name())
        print(e.get_dbus_message())
        if "UnknownObject" in e.get_dbus_name():
            print("Try scanning first to resolve this problem")
        return bluetooth_constants.RESULT_EXCEPTION
    else:
        print("Connected OK")
        return bluetooth_constants.RESULT_OK


def disconnect(device_inf: dbus.Interface) -> int:
    """Disconnect from the device using its interfaces.

    :param device_inf: The DBus interfaces for the device.
    :return: Status code
    """
    try:
        device_inf.Disconnect()
    except dbus.exceptions.DBusException as e:
        print("Failed to disconnect")
        print(e.get_dbus_name())
        print(e.get_dbus_message())
        return bluetooth_constants.RESULT_EXCEPTION
    else:
        print("Disconnected OK")
        return bluetooth_constants.RESULT_OK


def advertising_setup(bus: BusConnection) -> None:
    """Setup global variables used for advertising process.

    :param bus: The DBus BusConnection used for communications.
    :return: Nothing
    """
    global adv_mgr_interface, adv, signal_scan_add, signal_scan_update, \
        device_name

    if adv_mgr_interface is not None and adv is not None:
        print("Restart: Advertisement")
    else:
        print("Start: Advertisement")
        adapter_path = \
            bluetooth_constants.BLUEZ_NAMESPACE + \
            bluetooth_constants.ADAPTER_NAME
        adv_mgr_interface = \
            dbus.Interface(
                bus.get_object(
                    bluetooth_constants.BLUEZ_SERVICE_NAME, adapter_path),
                bluetooth_constants.ADVERTISING_MANAGER_INTERFACE)
        adv = Advertisement(bus, 0, 'peripheral', device_name)

    print("Advertising as:" + adv.local_name)


def advertising_initiate(
        bus: BusConnection,
        callback_added: Callable[[str, Dict[str, Dict[str, any]]],
                                 None],
        callback_updated: Callable[[str, Dict[str, any], dbus.Array, str],
                                   None],
        callback_adv_reply: Union[Callable[[None], None], None] = None,
        callback_adv_error: Union[Callable[[any], None], None] = None) -> None:
    """Initiate advertisement process.

    :param bus: The DBus BusConnection used for communications.
    :param callback_added: Callback to call when a device has been added during
    advertising process.
    :param callback_updated: Callback to call when a device has been updated
    during advertising process.
    :param callback_adv_reply: Callback to call when advertisement is set up
    :param callback_adv_error: Callback to call when there's an error with
    advertising.
    :return:
    """
    global signal_adv_add, signal_adv_update, adv_mgr_interface, adv

    if adv_mgr_interface is None:
        raise Exception("'adv_mgr_interface' must be initiated!")

    if adv is None:
        raise Exception("'adv' must be initiated!")

    for tries in range(5):
        print("Advertisement initiate: Trial #" + str(tries + 1) + ".")
        try:
            signal_adv_add = bus.add_signal_receiver(
                callback_added,
                dbus_interface=bluetooth_constants.DBUS_OM_IFACE,
                signal_name="InterfacesAdded")

            signal_adv_update = bus.add_signal_receiver(
                callback_updated,
                dbus_interface=bluetooth_constants.DBUS_PROPERTIES,
                signal_name="PropertiesChanged", path_keyword="path")

            if callback_adv_reply is None and callback_adv_error is None:
                adv_mgr_interface.RegisterAdvertisement(adv.get_path(), {})
            elif callback_adv_reply is not None and callback_adv_error is None:
                adv_mgr_interface.RegisterAdvertisement(
                    adv.get_path(), {},
                    reply_handler=callback_adv_reply)
            elif callback_adv_reply is None and callback_adv_error is not None:
                adv_mgr_interface.RegisterAdvertisement(
                    adv.get_path(), {},
                    error_handler=callback_adv_error)
            elif callback_adv_reply is not None \
                    and callback_adv_error is not None:
                adv_mgr_interface.RegisterAdvertisement(
                    adv.get_path(), {},
                    reply_handler=callback_adv_reply,
                    error_handler=callback_adv_error)

        except dbus.exceptions.DBusException as e:
            if e.get_dbus_name() == "org.bluez.Error.AlreadyExists":
                break
            else:
                print("Advertisement initiate: Failed to start!")
                print("-", e.get_dbus_name())
                print("-", e.get_dbus_message())
                if tries >= 4:
                    print("Failed to advertise!")
                    sys.exit(1)
        else:
            break

    print("Advertisement initiated!")


def advertising_start(bus: BusConnection, timeout: int) -> None:
    """Start device advertisement to become connectable.

    :param bus: The DBus BusConnection used for communications.
    :param timeout: Timeout for advertisement process in seconds.
    :return: Nothing
    """
    global current_step, adv_mgr_interface, adv, mainloop, signal_adv_add, \
        signal_adv_update, glob_connection_bus
    current_step = ProgramStates.STEP_ADVERTISING_START

    glob_connection_bus = bus

    advertising_setup(bus)
    advertising_initiate(bus, handle_advertisement_interfaces_added,
                         handle_advertisement_properties_changed,
                         handle_register_ad_cb,
                         handle_register_ad_error_cb)

    mainloop = GLib.MainLoop()

    if not timeout > 0:
        timeout = 30

    thread = Thread(target=thread_timeout_advertisement, args=(timeout,))
    thread.start()
    current_step = ProgramStates.STEP_ADVERTISING_ACTIVE
    mainloop.run()
    thread.join()


def advertising_stop() -> None:
    """Stop advertising process.

    :return: Nothing
    """
    global current_step, adv, adv_mgr_interface, mainloop, signal_adv_add, \
        signal_adv_update

    if mainloop is not None:
        mainloop.quit()

    if adv_mgr_interface is not None and adv is not None:
        adv_mgr_interface.UnregisterAdvertisement(adv.get_path())

    if signal_adv_add is not None:
        signal_adv_add.remove()

    if signal_adv_update is not None:
        signal_adv_update.remove()

    current_step = ProgramStates.STEP_ADVERTISING_DONE


def discover_and_advertise_start(bus: BusConnection, timeout: int) -> None:
    """Start the "discovery and advertising" process.

    :param bus: The DBus BusConnection used for communications.
    :param timeout: Timeout in seconds.
    :return: Nothing
    """
    global current_step, mainloop, adapter_interface, adv_mgr_interface, adv, \
        glob_connection_bus, signal_scan_add, signal_scan_remove, \
        signal_scan_update, device_name
    current_step = ProgramStates.STEP_DISCOVER_ADVERTISE_START

    # General Setup
    adapter_path = \
        bluetooth_constants.BLUEZ_NAMESPACE + \
        bluetooth_constants.ADAPTER_NAME

    # Discovery Setup
    adapter_object = \
        bus.get_object(
            bluetooth_constants.BLUEZ_SERVICE_NAME, adapter_path)
    adapter_interface = \
        dbus.Interface(
            adapter_object, bluetooth_constants.ADAPTER_INTERFACE)

    # Advertise Setup
    adv_mgr_interface = \
        dbus.Interface(
            bus.get_object(
                bluetooth_constants.BLUEZ_SERVICE_NAME, adapter_path),
            bluetooth_constants.ADVERTISING_MANAGER_INTERFACE)
    adv = Advertisement(bus, 0, 'peripheral', device_name)

    # Discovery Start
    adapter_interface.StartDiscovery(byte_arrays=True)

    signal_scan_add = bus.add_signal_receiver(
        handle_interface_added,
        dbus_interface=bluetooth_constants.DBUS_OM_IFACE,
        signal_name="InterfacesAdded")

    signal_scan_remove = bus.add_signal_receiver(
        handle_interface_removed,
        dbus_interface=bluetooth_constants.DBUS_OM_IFACE,
        signal_name="InterfacesRemoved")

    signal_scan_update = bus.add_signal_receiver(
        handle_properties_changed,
        dbus_interface=bluetooth_constants.DBUS_PROPERTIES,
        signal_name="PropertiesChanged",
        path_keyword="path")

    # Advertisement Start
    advertising_initiate(bus, handle_connection_monitor_interfaces_added,
                         handle_connection_monitor_properties_changed)

    # Bus for connections
    glob_connection_bus = bus

    # Begin
    mainloop = GLib.MainLoop()

    if not timeout > 0:
        timeout = 30

    thread_timeout = Thread(
        target=thread_timeout_discover_and_advertise,
        args=(timeout,))

    thread_connect = Thread(
        target=thread_connect_discover_and_advertise)

    thread_timeout.start()
    thread_connect.start()
    current_step = ProgramStates.STEP_DISCOVER_ADVERTISE_ACTIVE
    mainloop.run()
    thread_timeout.join()
    thread_connect.join()


def discover_and_advertise_stop() -> None:
    """Stop the "discovery and advertising" process.

    :return: Nothing
    """
    global current_step, mainloop, adapter_interface, adv_mgr_interface, adv, \
        signal_scan_add, signal_scan_remove, signal_scan_update

    if mainloop is not None:
        mainloop.quit()

    # Discovery Stop
    if adapter_interface is not None:
        adapter_interface.StopDiscovery()

    if signal_scan_add is not None:
        signal_scan_add.remove()

    if signal_scan_remove is not None:
        signal_scan_remove.remove()

    if signal_scan_update is not None:
        signal_scan_update.remove()

    # Advertise Stop
    if adv_mgr_interface is not None and adv is not None:
        adv_mgr_interface.UnregisterAdvertisement(adv.get_path())

    current_step = ProgramStates.STEP_DISCOVER_ADVERTISE_DONE


def connection_monitor_start(
        bus: BusConnection,
        devices_conn: Union[Dict[str, Dict[str, any]], None] = None) -> None:
    """Start the connection monitoring process

    :param bus: The DBus BusConnection used for communications.
    :param devices_conn: The devices to connect to
    :return: Nothing
    """
    global current_step, mainloop, glob_connection_bus
    current_step = ProgramStates.STEP_CONNECTION_START

    glob_connection_bus = bus

    if devices_conn is not None and len(devices_conn) > 0:
        connect_to_devices(bus, devices_conn)

    # Scan (to get RSSI)
    global adapter_interface
    if adapter_interface is not None:
        print("Restart: Discovery")
    else:
        print("Start: Discovery")
        adapter_path = \
            bluetooth_constants.BLUEZ_NAMESPACE + \
            bluetooth_constants.ADAPTER_NAME
        adapter_object = \
            bus.get_object(
                bluetooth_constants.BLUEZ_SERVICE_NAME, adapter_path)
        adapter_interface = \
            dbus.Interface(
                adapter_object, bluetooth_constants.ADAPTER_INTERFACE)

    adapter_interface.StartDiscovery(byte_arrays=True)

    # Advertise (to show RSSI):
    advertising_setup(bus)
    advertising_initiate(bus, handle_connection_monitor_interfaces_added,
                         handle_connection_monitor_properties_changed)

    thread = Thread(target=thread_check_connected_devices, args=(bus,))
    thread.start()
    current_step = ProgramStates.STEP_CONNECTION_ACTIVE
    mainloop.run()
    thread.join()


def connection_monitor_stop() -> None:
    """Stop the connection monitoring process.

    :return: Nothing
    """
    global current_step, mainloop

    disconnect_from_all_devices()

    if mainloop is not None:
        mainloop.quit()

    # Discover
    global adapter_interface
    if adapter_interface is not None:
        adapter_interface.StopDiscovery()

    # Advertise
    global adv_mgr_interface, adv, signal_adv_add, signal_adv_update
    if adv_mgr_interface is not None and adv is not None:
        adv_mgr_interface.UnregisterAdvertisement(adv.get_path())

    if signal_adv_add is not None:
        signal_adv_add.remove()

    if signal_adv_update is not None:
        signal_adv_update.remove()

    current_step = ProgramStates.STEP_CONNECTION_DONE


# ------ [ Methods - DBus & BlueZ - Event Handlers ] --------------------------


def handle_interface_added(
        path: str, interfaces: Dict[str, Dict[str, any]]) -> None:
    """Handler for when BlueZ have found a new device. Will update the found
    devices accordingly.

    :param path: The DBus ObjectPath to the newly found device.
    :param interfaces: The DBus interfaces for the found device.
    :return: Nothing
    """
    global current_step, devices_found, adv_mgr_interface, adv

    if bluetooth_constants.DEVICE_INTERFACE not in interfaces:
        return

    device_properties = interfaces[bluetooth_constants.DEVICE_INTERFACE]
    devices_found[path] = device_properties
    print_info_found_device(path)


def handle_interface_removed(
        path: str, interfaces: Dict[str, Dict[str, any]]) -> None:
    """Handler for when BlueZ no longer is able to see a device. Will update
    the found devices accordingly.

    :param path: The DBus ObjectPath to the removed device.
    :param interfaces: The DBus interfaces for the removed device.
    :return: Nothing
    """
    global current_step

    if bluetooth_constants.DEVICE_INTERFACE not in interfaces or \
            path not in devices_found:
        return

    print_info_removed_device(path)
    del devices_found[path]


def handle_properties_changed(
        interface: str, changed: Dict[str, any], invalidated: dbus.Array,
        path: str) -> None:
    """Handler for when BlueZ have updated the info for an existing device.
    Will update the found devices accordingly.

    :param interface: The DBus interfaces for the changed device.
    :param changed: The DBus properties dict with changed properties for the
    device.
    :param invalidated: The DBus array of properties that are now invalidated.
    :param path: The DBus ObjectPath to the device.
    :return: Nothing.
    """
    global current_step

    if interface != bluetooth_constants.DEVICE_INTERFACE:
        return

    print_info_updated_device(path, changed)

    if path in devices_found:
        devices_found[path].update(changed)
    else:
        devices_found[path] = changed


def handle_register_ad_cb() -> None:
    """Handle successful registration of advertisement.

    :return: Nothing
    """
    print('Advertisement registered OK')


def handle_register_ad_error_cb(error: any) -> None:
    global mainloop
    print(f"Error: Failed to register advertisement {error}")
    mainloop.quit()


def handle_advertisement_interfaces_added(
        path: str, interfaces: Dict[str, Dict[str, any]]) -> None:
    """Handler for when BlueZ have found a new device. Will update connected
    devices accordingly.

    :param path: The DBus ObjectPath to the newly found device.
    :param interfaces: The DBus interfaces for the found device.
    :return: Nothing
    """
    if bluetooth_constants.DEVICE_INTERFACE in interfaces:
        properties = interfaces[bluetooth_constants.DEVICE_INTERFACE]

        if "Connected" in properties:

            print_info_dated_msg(
                "Advertisement add", bluetooth_utils.dbus_to_python(path),
                "connected:", properties["Connected"])

            if properties["Connected"] and path not in devices_connected:
                print_info_dated_msg("ADD: Added to connected...")
                devices_connected[path] = properties
            elif not properties["Connected"] and path in devices_connected:
                print_info_dated_msg("ADD: Removed from connected...")
                del devices_connected[path]


def handle_advertisement_properties_changed(
        interface: str, changed: Dict[str, any], invalidated: dbus.Array,
        path: str) -> None:
    """Handler for when BlueZ have updated the info for an existing device.
    Will update connected devices accordingly.

    :param interface: The DBus interface for the changed device.
    :param changed: The DBus properties dict with changed properties for the
    device.
    :param invalidated: The DBus array of properties that are now invalidated.
    :param path: The DBus ObjectPath to the device.
    :return: Nothing.
    """
    global glob_connection_bus

    if interface == bluetooth_constants.DEVICE_INTERFACE:
        print("Advertisement change", bluetooth_utils.dbus_to_python(path),
              end=" ")

        if "Connected" in changed:

            print("connected:", changed["Connected"])

            if changed["Connected"] and path not in devices_connected:
                print_info_dated_msg("UPD: Added to connected...")
                device_properties = \
                    get_device_properties_interface(glob_connection_bus, path)
                devices_connected[path] = \
                    device_properties.GetAll(
                        bluetooth_constants.DEVICE_INTERFACE)

            elif not changed["Connected"] and path in devices_connected:
                print_info_dated_msg("UPD: Removed from connected...")
                del devices_connected[path]

        else:
            print("...")


def handle_connection_monitor_interfaces_added(
        path: str, interfaces: Dict[str, Dict[str, any]]) -> None:
    """Handler for when BlueZ have found a new device. Will update connected
    devices accordingly.

    :param path: The DBus ObjectPath to the newly found device.
    :param interfaces: The DBus interfaces for the found device.
    :return: Nothing
    """
    global mutex_role_to_device

    if bluetooth_constants.DEVICE_INTERFACE in interfaces:
        properties = interfaces[bluetooth_constants.DEVICE_INTERFACE]

        if "Connected" in properties:
            mutex_role_to_device.acquire()
            if properties["Connected"] and path not in devices_connected:
                devices_connected[path] = properties

                if path not in role_to_device or \
                        role_to_device[path] == NodeModes.NONE:
                    print_info_dated_msg("Device initiated connection:",
                                         bluetooth_utils.dbus_to_python(path))
                    role_to_device[path] = NodeModes.PERIPHERAL
                elif role_to_device[path] == NodeModes.CENTRAL:
                    print_info_dated_msg("Already connected as central!")

            elif not properties["Connected"] and path in devices_connected:
                del devices_connected[path]
                print_info_dated_msg("Device disconnected:",
                                     bluetooth_utils.dbus_to_python(path))
                role_to_device[path] = NodeModes.NONE

            mutex_role_to_device.release()


def handle_connection_monitor_properties_changed(
        interface: str, changed: Dict[str, any], invalidated: dbus.Array,
        path: str) -> None:
    """Handler for when BlueZ have updated the info for an existing device.
    Will update connected devices accordingly.

    :param interface: The DBus interface for the changed device.
    :param changed: The DBus properties dict with changed properties for the
    device.
    :param invalidated: The DBus array of properties that are now invalidated.
    :param path: The DBus ObjectPath to the device.
    :return: Nothing.
    """
    global glob_connection_bus, mutex_role_to_device

    if interface == bluetooth_constants.DEVICE_INTERFACE:
        if "Connected" in changed:
            mutex_role_to_device.acquire()
            if changed["Connected"] and path not in devices_connected:
                device_properties = \
                    get_device_properties_interface(glob_connection_bus, path)
                devices_connected[path] = \
                    device_properties.GetAll(
                        bluetooth_constants.DEVICE_INTERFACE)

                if path not in role_to_device or \
                        role_to_device[path] == NodeModes.NONE:
                    print_info_dated_msg(
                        "Device initiated connection:",
                        bluetooth_utils.dbus_to_python(path))
                    role_to_device[path] = NodeModes.PERIPHERAL

                elif role_to_device[path] == NodeModes.CENTRAL:
                    print_info_dated_msg("Already connected as central!")

            elif not changed["Connected"] and path in devices_connected:
                del devices_connected[path]
                print_info_dated_msg("Device disconnected:",
                                     bluetooth_utils.dbus_to_python(path))
                role_to_device[path] = NodeModes.NONE

            mutex_role_to_device.release()


# ------ [ Main Program ] -----------------------------------------------------
# TODO: Implement run_collision_avoidance
#   - Discover + Advertise for X seconds
#   - Found device have own name? Change name


def run_device_discovery(bus: BusConnection, scan_time: int = 0) -> None:
    """Begin device discovery by starting thread to look for seen devices and
    then start the scan process. Scan for specified amount of time or
    60 seconds.

    :param bus: The DBus BusConnection used for communications.
    :param scan_time: How long to scan for in seconds.
    :return: Nothing
    """
    # Setup
    find_known_devices(bus)

    if not scan_time > 0:
        scan_time = 60

    # Information
    print("Scan for", scan_time, "seconds..")

    # Scanning
    thread = Thread(target=thread_check_seen_devices, args=(bus,))
    thread.start()
    discovery_start(bus, scan_time * 1000)
    thread.join()


def run_device_advertisement(bus: BusConnection, adv_time: int = 0) -> None:
    """Begin device advertisement by starting advertisement process.
    Will advertise for specified amount of time or for 60 seconds.

    :param bus: The DBus BusConnection used for communications.
    :param adv_time: How long to advertise for in seconds.
    :return: Nothing
    """
    global mainloop, adv_mgr_interface, adv

    if not adv_time > 0:
        adv_time = 60

    # Information
    print("Advertise for", adv_time, "seconds..")

    # Advertisement
    advertising_start(bus, adv_time)


def run_connection_monitor_mode_auto_node(bus: BusConnection) -> None:
    """Run connection monitor mode in automatic node mode where the device may
    become a central or a peripheral node.

    :param bus: The DBus BusConnection used for communications.
    :return: Nothing
    """
    # Get already known devices
    find_known_devices(bus)

    while len(devices_connected) == 0:
        # Discover and advertise
        discover_and_advertise_start(bus, 60)

        if len(devices_connected) == 0:
            print_info_dated_msg(
                "Found no devices to connect to. Trying again.")

    # Found interesting
    print_info_dated_msg("Connected to device(s)! Begin monitoring..")

    # Start connection monitor
    connection_monitor_start(bus)


def run_connection_monitor_mode_central_node(bus: BusConnection) -> None:
    """Run connection monitor mode in central node mode.

    :param bus: The DBus BusConnection used for communications.
    :return: Nothing
    """

    # Get already known devices
    find_known_devices(bus)

    while len(devices_connected) == 0:
        # Scan for peripherals for 30 seconds
        run_device_discovery(bus, 30)

        # Get matching devices
        matching_devices = get_matching_and_active_devices()

        # Connect to found devices
        if len(matching_devices) > 0:
            connect_to_devices(bus, matching_devices)
        else:
            print_info_dated_msg(
                "Found no devices to connect to. Trying again.")

    # Found interesting
    print_info_dated_msg("Connected to device(s)! Begin monitoring..")

    # Start connection monitor
    connection_monitor_start(bus)


def run_connection_monitor_mode_peripheral_node(bus: BusConnection) -> None:
    """Run connection monitor mode in peripheral node mode.

    :param bus: The DBus BusConnection used for communications.
    :return: Nothing
    """

    # Get already known devices
    find_known_devices(bus)

    while len(devices_connected) == 0:
        # Advertise for 30 seconds
        run_device_advertisement(bus, 30)

        if len(devices_connected) == 0:
            print_info_dated_msg(
                "Found no devices to connect to. Trying again.")

    # Found interesting
    print_info_dated_msg("Connected to device(s)! Begin monitoring..")

    # Start connection monitor
    connection_monitor_start(bus)


if __name__ == '__main__':
    # Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--program", help="Program mode", nargs='?',
                        choices=['monitor', 'message'],
                        const="monitor", default="monitor", type=str)
    parser.add_argument("-n", "--node", help="Node mode", nargs='?',
                        choices=['auto', 'central', 'peripheral'],
                        const="auto", default="auto", type=str)
    args = parser.parse_args()

    # Bus setup
    bus_connection = initialize_dbus()

    # Register signal handlers
    register_signal_handlers()

    # Program Modes
    if args.program == "monitor":
        print("Program mode: Connection Monitor")
        if args.node == "auto":
            print("Node mode: Automatic")
            run_connection_monitor_mode_auto_node(bus_connection)

        elif args.node == "central":
            print("Node mode: Central")
            run_connection_monitor_mode_central_node(bus_connection)

        elif args.node == "peripheral":
            print("Node mode: Peripheral")
            run_connection_monitor_mode_peripheral_node(bus_connection)

    elif args.program == "message":
        print("Program mode: Message")
        if args.node == "auto":
            print("Node mode: Automatic")
            # TODO: Implement

        elif args.node == "central":
            print("Node mode: Central")
            # TODO: Implement

        elif args.node == "peripheral":
            print("Node mode: Peripheral")
            # TODO: Implement

    print("Done with program!")

# Build 3
