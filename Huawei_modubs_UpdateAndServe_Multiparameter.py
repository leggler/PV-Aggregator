import logging
from logging.handlers import RotatingFileHandler
from threading import Thread, Lock
import time
import yaml
import signal
import sys
from typing import Dict, Tuple, Any
from flask import Flask, jsonify

from sun2000_modbus import inverter, registers
from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.device import ModbusDeviceIdentification

# Configure logging to file and console
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_file = "/tmp/logs/solar_power_aggregator.log"

file_handler = RotatingFileHandler(log_file, maxBytes=3 * 1024 * 1024, backupCount=2)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.WARNING)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.WARNING)

logging.basicConfig(level=logging.WARNING, handlers=[file_handler, console_handler])

# Create Flask app
app = Flask(__name__)

# Load configuration from YAML file
with open('config.yaml', 'r') as config_file:
    config: Dict[str, Dict[str, str]] = yaml.safe_load(config_file)

HUAWEI_INVERTERS: Dict[str, str] = config['inverters']

# Measurements to read from each inverter
MEASUREMENTS: Dict[str, registers.InverterEquipmentRegister] = {
    "active_power": registers.InverterEquipmentRegister.ActivePower,
    "Accumulated_energy_yield": registers.InverterEquipmentRegister.AccumulatedEnergyYield,
}

# Calculation of the number of registers:
NUM_MEASUREMENTS: int = len(MEASUREMENTS)
MEASUREMENTS_REGISTERS: int = NUM_MEASUREMENTS * 2
TOTAL_REGISTER_COUNT: int = MEASUREMENTS_REGISTERS + 1

# Create a thread-safe Modbus datastore
data_lock: Lock = Lock()
datastore: ModbusSequentialDataBlock = ModbusSequentialDataBlock(0, [0] * TOTAL_REGISTER_COUNT)
context: ModbusServerContext = ModbusServerContext(slaves=ModbusSlaveContext(hr=datastore), single=True)

inverter_dict: Dict[str, inverter.Sun2000] = {}
failed_reading_counter: int = 0  # Global counter for failed readings
detailed_values_global: Dict[str, Dict[str, Dict[str, Any]]] = {}  # Global dictionary to store detailed values

def connect_to_inverter(name: str, ip: str) -> inverter.Sun2000:
    """
    Connects to an inverter and returns the inverter object.
    :param name: Name of the inverter.
    :param ip: IP address of the inverter.
    :return: Inverter object.
    """
    inv: inverter.Sun2000 = inverter.Sun2000(unit=1, host=ip, timeout=10, wait=1.5)
    try:
        inv.connect()
        logging.info(f"Connected to {name} ({ip})")
    except Exception as e:
        logging.error(f"Could not connect to {name} ({ip}): {e}")
    return inv

def create_inverter_objects() -> Dict[str, inverter.Sun2000]:
    """
    Creates inverter objects for each defined IP and attempts an initial connection.
    :return: Dictionary of inverter objects.
    """
    inverters: Dict[str, inverter.Sun2000] = {}
    for name, ip in HUAWEI_INVERTERS.items():
        inverters[name] = connect_to_inverter(name, ip)
    return inverters

def reconnect_inverter(inv: inverter.Sun2000, name: str) -> bool:
    """
    Attempts to reconnect to an inverter.
    :param inv: Inverter object.
    :param name: Name of the inverter.
    :return: True if reconnection was successful, False otherwise.
    """
    try:
        inv.disconnect()
        time.sleep(2)
        inv.connect()
        return True
    except Exception as re:
        logging.error(f"Reconnection failed for {name}: {re}")
        return False

def read_measurement_values(inverters: Dict[str, inverter.Sun2000], last_successful: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    Reads measurements from inverters and returns detailed values for all measurements.
    :param inverters: Dictionary of inverter objects.
    :param last_successful: Dictionary of last successful read values.
    :return: Dictionary containing detailed measurement values and update status.
    """
    global failed_reading_counter, detailed_values_global
    detailed_values: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for name, inv in inverters.items():
        detailed_values[name] = {}
        for measurement, reg_enum in MEASUREMENTS.items():
            try:
                value: int = inv.read_raw_value(reg_enum)
                if value is None:
                    raise ValueError(f"Inverter {name}, measurement {measurement}: Received None as value")

                if measurement == "Accumulated_energy_yield":
                    value = int(value / 100)  # for result in kWh

                last_successful[name][measurement] = value
                updated: bool = True
            except Exception as e:
                logging.error(f"Error reading {measurement} from {name}: {e}")
                failed_reading_counter += 1
                logging.error(f"Failed reading counter incremented to {failed_reading_counter} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
                updated = False
                reconnect_inverter(inv, name)
                value = last_successful[name][measurement]

            detailed_values[name][measurement] = {'value': value, 'updated': updated, 'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}
            logging.debug(f"{name} - {measurement}: {value} (Updated: {updated})")

    detailed_values_global = detailed_values  # Update global detailed values
    return detailed_values

def aggregate_values(detailed_values: Dict[str, Dict[str, Dict[str, Any]]]) -> Tuple[Dict[str, int], int]:
    """
    Aggregates the detailed measurement values.
    :param detailed_values: Dictionary of detailed measurement values.
    :return: Tuple of aggregated values and count of valid readings.
    """
    aggregated_values: Dict[str, int] = {key: 0 for key in MEASUREMENTS.keys()}
    valid_readings_count: int = 0

    for name, measurements in detailed_values.items():
        for measurement, data in measurements.items():
            aggregated_values[measurement] += data['value']
            if data['updated']:
                valid_readings_count += 1

    return aggregated_values, valid_readings_count

def update_modbus_registers(aggregated_values: Dict[str, int], valid_readings_count: int) -> None:
    """
    Updates the Modbus registers in a thread-safe manner.
    :param aggregated_values: Dictionary of aggregated measurement values.
    :param valid_readings_count: Count of valid readings.
    """
    with data_lock:
        register_offset: int = 0
        for measurement, total_value in aggregated_values.items():
            low: int = total_value & 0xFFFF
            high: int = (total_value >> 16) & 0xFFFF
            context[0].setValues(3, register_offset, [high, low])
            logging.debug(f"Updated {measurement}: {total_value} (Regs {register_offset} & {register_offset + 1})")
            register_offset += 2

        context[0].setValues(3, register_offset, [valid_readings_count])
        logging.debug(f"Updated Valid Readings Count: {valid_readings_count} (Reg {register_offset})")

def main_loop(inverters: Dict[str, inverter.Sun2000], last_successful: Dict[str, Dict[str, int]]) -> None:
    """
    Main loop to read measurement values, aggregate them, and update Modbus registers.
    :param inverters: Dictionary of inverter objects.
    :param last_successful: Dictionary of last successful read values.
    """
    while True:
        detailed_values: Dict[str, Dict[str, Dict[str, Any]]] = read_measurement_values(inverters, last_successful)
        aggregated_values, valid_readings_count = aggregate_values(detailed_values)
        update_modbus_registers(aggregated_values, valid_readings_count)
        logging.info("Aggregated Values: %s, Valid Readings Count: %d", aggregated_values, valid_readings_count)
        time.sleep(5)

def start_modbus_server() -> None:
    """
    Starts the Modbus TCP server with identification information.
    """
    identity: ModbusDeviceIdentification = ModbusDeviceIdentification()
    identity.VendorName = 'SolarPower'
    identity.ProductCode = 'SP'
    identity.VendorUrl = 'https://example.com'
    identity.ProductName = 'Solar Power Aggregator'
    identity.ModelName = 'SP1000'
    identity.MajorMinorRevision = '1.0'

    StartTcpServer(context, identity=identity, address=("0.0.0.0", 502))

def signal_handler(sig: int, frame: Any) -> None:
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

@app.route('/readings', methods=['GET'])
def get_readings():
    """
    Endpoint to get the current detailed readings.
    """
    return jsonify({
        'failed_reading_counter': failed_reading_counter,
        'detailed_values': detailed_values_global
    })

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    inverter_dict = create_inverter_objects()

    last_successful: Dict[str, Dict[str, int]] = {name: {measurement: 0 for measurement in MEASUREMENTS} for name in inverter_dict}

    update_thread: Thread = Thread(target=main_loop, args=(inverter_dict, last_successful))
    update_thread.daemon = True
    update_thread.start()

    # Start Flask server on a separate thread
    flask_thread = Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 5000})
    flask_thread.daemon = True
    flask_thread.start()

    start_modbus_server()