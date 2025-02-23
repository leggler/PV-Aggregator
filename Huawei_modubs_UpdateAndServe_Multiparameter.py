import logging
from threading import Thread, Lock
import time
import yaml
import signal
import sys

from sun2000_modbus import inverter, registers
from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.device import ModbusDeviceIdentification

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load configuration from YAML file
with open('config.yaml', 'r') as config_file:
    config = yaml.safe_load(config_file)

HUAWEI_INVERTERS: dict[str, str] = config['inverters']

# Measurements to read from each inverter
MEASUREMENTS: dict[str, object] = {
    "active_power": registers.InverterEquipmentRegister.ActivePower,
    "Accumulated_energy_yield": registers.InverterEquipmentRegister.AccumulatedEnergyYield,
}

# Calculation of the number of registers:
# Each measurement is stored as a 32-bit value (2 consecutive 16-bit registers)
NUM_MEASUREMENTS: int = len(MEASUREMENTS)
MEASUREMENTS_REGISTERS: int = NUM_MEASUREMENTS * 2
# Additionally, one register is reserved for the count of connected inverters (UINT16)
TOTAL_REGISTER_COUNT: int = MEASUREMENTS_REGISTERS + 1

# Create a thread-safe Modbus datastore
data_lock: object = Lock()
datastore: object = ModbusSequentialDataBlock(0, [0] * TOTAL_REGISTER_COUNT)
context: object = ModbusServerContext(slaves=ModbusSlaveContext(hr=datastore), single=True)

inverter_dict: dict = {}

def create_inverter_objects() -> dict[str, object]:
    """
    Creates inverter objects for each defined IP and attempts an initial connection.
    :return: Dictionary of inverter objects.
    """
    inverters = {}
    for name, ip in HUAWEI_INVERTERS.items():
        inv: object = inverter.Sun2000(unit=1, host=ip, timeout=10, wait=1)
        try:
            inv.connect()
            logging.info(f"Connected to {name} ({ip})")
        except Exception as e:
            logging.error(f"Could not connect to {name} ({ip}): {e}")
        inverters[name] = inv
    return inverters


def read_measurement_values(inverters: dict, last_successful: dict) -> tuple[dict, int]:
    """
    Reads measurements from inverters and aggregates the values.
    :param inverters: Dictionary of inverter objects.
    :param last_successful: Dictionary of last successful read values.
    :return: Tuple of aggregated values and connected inverters count.
    """
    aggregated_values: dict[str, int] = {key: 0 for key in MEASUREMENTS.keys()}
    connected_inverters_count: int = 0

    # Iterate through all inverters
    for name, inv in inverters.items():
        #iterate throuhg measurments (power, meter)
        for measurement, reg_enum in MEASUREMENTS.items():
            # Attempt to read the raw value
            try:
                value = inv.read_raw_value(reg_enum)
                if value is None:
                    raise ValueError(f"Inverter {name}, measurement {measurement}: Received None as value")
                # If this is the accumulated energy yield, divide the value by 100 to get MWh(?)
                if measurement == "Accumulated_energy_yield":
                    value = int(value / 100)
                # Update the last successful reading for this inverter and measurement.
                last_successful[name][measurement] = value

            except Exception as e:
                logging.error(f"Error reading {measurement} from {name}: {e}")
                try:
                    inv.disconnect()
                    time.sleep(2)
                    inv.connect()
                    logging.info(f"Reconnected to {name}")
                except Exception as re:
                    logging.error(f"Reconnection failed for {name}: {re}")
                # If reading fails, use the last successful value (defaults to 0 if never updated)
                value = last_successful[name][measurement]

            aggregated_values[measurement] += value
            logging.debug(f"{name} - {measurement}: {value}")

        # Count inverter if it is connected
        if inv.isConnected():
            connected_inverters_count += 1

    return aggregated_values, connected_inverters_count


def update_modbus_registers(aggregated_values: dict, connected_inverters_count: int) -> None:
    """
    Updates the Modbus registers in a thread-safe manner.
    :param aggregated_values: Dictionary of aggregated measurement values.
    :param connected_inverters_count: Count of connected inverters.
    """
    with data_lock:
        register_offset: int = 0
        # Store the 32-bit aggregated value as two 16-bit registers (high and low parts)
        for measurement, total_value in aggregated_values.items():
            low = total_value & 0xFFFF
            high = (total_value >> 16) & 0xFFFF
            context[0].setValues(3, register_offset, [high, low])
            logging.debug(f"Updated {measurement}: {total_value} (Regs {register_offset} & {register_offset + 1})")
            register_offset += 2
        # Write the count of connected inverters to the additional register
        context[0].setValues(3, register_offset, [connected_inverters_count])
        logging.info(f"Updated Connected Inverters Count: {connected_inverters_count} (Reg {register_offset})")


def main_loop(inverters: dict, last_successful: dict) -> None:
    """
    Main loop to read measurement values and update Modbus registers.
    :param inverters: Dictionary of inverter objects.
    :param last_successful: Dictionary of last successful read values.
    """
    while True:
        aggregated_values, connected_inverters_count = read_measurement_values(inverters, last_successful)
        update_modbus_registers(aggregated_values, connected_inverters_count)
        logging.info("Aggregated Values: %s", aggregated_values)
        time.sleep(5)


def start_modbus_server() -> None:
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


def signal_handler(sig, frame) -> None:
    """
    Handles termination signals to gracefully shut down the server.
    """
    logging.info('Shutting down gracefully...')
    for name, inv in inverter_dict.items():
        try:
            inv.disconnect()
            logging.info(f"Disconnected from {name}")
        except Exception as e:
            logging.error(f"Error disconnecting from {name}: {e}")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    inverter_dict = create_inverter_objects()

    last_successful: dict[str, dict[str, int]] = {name: {measurement: 0 for measurement in MEASUREMENTS} for name in inverter_dict}

    update_thread = Thread(target=main_loop, args=(inverter_dict, last_successful))
    update_thread.daemon = True
    update_thread.start()

    start_modbus_server()