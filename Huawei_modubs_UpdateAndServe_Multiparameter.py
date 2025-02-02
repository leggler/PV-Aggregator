from sun2000_modbus import inverter, registers
from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.device import ModbusDeviceIdentification
from threading import Thread, Lock
import time




# Inverter IP addresses
HUAWEI_INVERTERS = {
    "H10-11": "10.10.45.100",
    "H3": "10.10.45.101",
    "Staubx-gr-2": "10.10.45.102",
    "H2-3": "10.10.45.103",
    "Staubx-gr-1": "10.10.45.104",
    "Staubx-kl": "10.10.45.116",
    "H5-6": "10.10.45.120"
}

# Measurements to read from each inverter
MEASUREMENTS = {
    "active_power": registers.InverterEquipmentRegister.ActivePower,
    "Accumulated_energy_yield": registers.InverterEquipmentRegister.AccumulatedEnergyYield,
}

# Calculation of the number of registers:
# Each measurement is stored as a 32-bit value (2 consecutive 16-bit registers)
NUM_MEASUREMENTS = len(MEASUREMENTS)
MEASUREMENTS_REGISTERS = NUM_MEASUREMENTS * 2
# Additionally, one register is reserved for the count of connected inverters (UINT16)
TOTAL_REGISTER_COUNT = MEASUREMENTS_REGISTERS + 1

# Create a thread-safe Modbus datastore
data_lock = Lock()
datastore = ModbusSequentialDataBlock(0, [0] * TOTAL_REGISTER_COUNT)
context = ModbusServerContext(slaves=ModbusSlaveContext(hr=datastore), single=True)


def create_inverter_objects():
    """
    Creates inverter objects for each defined IP and attempts an initial connection.
    """
    inverters = {}
    for name, ip in HUAWEI_INVERTERS.items():
        inv = inverter.Sun2000(unit=1, host=ip, timeout=10, wait=1)
        try:
            inv.connect()
            print(f"[OK] Connected to {name} ({ip})")
        except Exception as e:
            print(f"[ERROR] Could not connect to {name} ({ip}): {e}")
        inverters[name] = inv
    return inverters


def update_inverter_values(inverters):
    """
    Continuously polls measurements from inverters, aggregates them,
    and updates the Modbus registers. If a measurement read fails,
    the last successful value is used (or 0 if never read successfully).
    """
    # Initialize a dictionary to store the last successful read for each inverter and measurement.
    last_successful = {name: {measurement: 0 for measurement in MEASUREMENTS} for name in inverters}

    while True:
        aggregated_values = {key: 0 for key in MEASUREMENTS.keys()}
        connected_inverters_count = 0

        # Iterate through all inverters
        for name, inv in inverters.items():
            for measurement, reg_enum in MEASUREMENTS.items():
                try:
                    # Attempt to read the raw value
                    value = inv.read_raw_value(reg_enum)
                    if value is None:
                        raise ValueError("Received None as value")

                    # If this is the accumulated energy yield, divide the value by 100
                    if measurement == "Accumulated_energy_yield":
                        value = int(value / 100)

                    # Update the last successful reading for this inverter and measurement.
                    last_successful[name][measurement] = value
                except Exception as e:
                    print(f"[ERROR] Error reading {measurement} from {name}: {e}")
                    try:
                        inv.disconnect()
                        time.sleep(2)
                        inv.connect()
                        print(f"[OK] Reconnected to {name}")
                    except Exception as re:
                        print(f"[ERROR] Reconnection failed for {name}: {re}")
                    # If reading fails, use the last successful value (defaults to 0 if never updated)
                    value = last_successful[name][measurement]

                aggregated_values[measurement] += value
                print(f"{name} - {measurement}: {value}")

            # Count inverter if it is connected
            if inv.isConnected():
                connected_inverters_count += 1

        # Update the Modbus registers in a thread-safe manner
        with data_lock:
            register_offset = 0
            for measurement, total_value in aggregated_values.items():
                # Store the 32-bit aggregated value as two 16-bit registers (high and low parts)
                low = total_value & 0xFFFF
                high = (total_value >> 16) & 0xFFFF
                context[0].setValues(3, register_offset, [high, low])
                print(f"Updated {measurement}: {total_value} (Regs {register_offset} & {register_offset + 1})")
                register_offset += 2

            # Write the count of connected inverters to the additional register
            context[0].setValues(3, register_offset, [connected_inverters_count])
            print(f"Updated Connected Inverters Count: {connected_inverters_count} (Reg {register_offset})")

        print("Aggregated Values:", aggregated_values)
        time.sleep(5)  # Polling interval


def start_modbus_server():
    """
    Starts the Modbus TCP server with identification information.
    """
    identity = ModbusDeviceIdentification()
    identity.VendorName = 'SolarPower'
    identity.ProductCode = 'SP'
    identity.VendorUrl = 'https://example.com'
    identity.ProductName = 'Solar Power Aggregator'
    identity.ModelName = 'SP1000'
    identity.MajorMinorRevision = '1.0'

    StartTcpServer(context, identity=identity, address=("0.0.0.0", 502))


if __name__ == "__main__":
    inverter_dict = create_inverter_objects()

    update_thread = Thread(target=update_inverter_values, args=(inverter_dict,))
    update_thread.daemon = True  # Daemon thread will close when the main program exits
    update_thread.start()

    start_modbus_server()
