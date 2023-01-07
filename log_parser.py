import os
import sys
import re
from typing import List, Tuple

# ------ [ Constants ] --------------------------------------------------------

RE_TIMED_MESSAGE: str = r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - "
RE_BT_ADDR: str = r"[A-F\d]{2}:[A-F\d]{2}:[A-F\d]{2}:[A-F\d]{2}:[A-F\d]{2}:" \
                  r"[A-F\d]{2}"

RE_CONNECTION_MONITOR_START: str = RE_TIMED_MESSAGE + \
                                   r"Connected to device\(s\)! Begin " \
                                   r"monitoring\.\.$"
RE_CONNECTION_MONITOR_END: str = RE_TIMED_MESSAGE + \
                                 r"No connected devices\.\.\. Going back to " \
                                 r"automatic connection mode\.$"

RE_NODE_NAMES: str = r"[ABab]\d{1,2}"
RE_PERSON_NAMES: str = r"[A-Za-zÅÄÖåäö]+"

RE_SECT_NAMED_FROM_TO: str = r"^//(" + RE_PERSON_NAMES + r")[:.] (" + \
                             RE_NODE_NAMES + r") to (" + RE_NODE_NAMES + r")$"
RE_SECT_ANON_FROM_TO: str = r"^//(" + RE_NODE_NAMES + r") to (" + \
                            RE_NODE_NAMES + r")$"
RE_SECT_ANON_FROM_TO_SHORT: str = r"^(" + RE_NODE_NAMES + r")(" + \
                                  RE_NODE_NAMES + r")$"
RE_SECT_NEGATIVE_FROM: str = r"^//(" + RE_PERSON_NAMES + r")[:.] (" + \
                             RE_NODE_NAMES + r") above$"
RE_SECT_NAMED_STOP: str = r"^//(" + RE_PERSON_NAMES + r")[:.] stop$"
RE_SECT_ANON_STOP: str = r"^//stop$"

RE_SECT_MEASUREMENT: str = RE_TIMED_MESSAGE + r"([^(]+) \((" + RE_BT_ADDR + \
                           r")\): (-?\d+) dBm"


# ------ [ Helper Methods ] ---------------------------------------------------


def print_program_usage() -> None:
    """Print information about how to execute the program.

    :return: Nothing
    """
    print("usage: python3 log_parser.py <log_file_path> "
          "[<log_file_path2> ...]")


# ------ [ Log Parsing ] ------------------------------------------------------


def get_connection_monitoring_sections(
        raw_log_lines: List[str]) -> List[List[str]]:
    """Get the "connection monitoring" sections from the raw log

    :param raw_log_lines: A list of lines from the raw log.
    :return: A list of sections from the raw log.
    """
    monitoring_sections = []

    current_section_open = False
    current_monitoring_section = []

    for log_line in raw_log_lines:
        if re.search(RE_CONNECTION_MONITOR_START, log_line):
            current_section_open = True
        elif re.search(RE_CONNECTION_MONITOR_END, log_line):
            if not current_section_open:
                continue

            monitoring_sections.append(current_monitoring_section.copy())
            current_section_open = False
            current_monitoring_section = []

        elif current_section_open:
            current_monitoring_section.append(log_line)

    if current_section_open:
        monitoring_sections.append(current_monitoring_section.copy())

    return monitoring_sections


def get_connection_monitoring_measurements(
        monitoring_sections: List[List[str]]) -> \
        List[Tuple[str, str, str, str, str]]:

    measurements = []
    current_section = None, None

    for section_num, log_section in enumerate(monitoring_sections):

        for log_line in log_section:
            sect_named_from_to = \
                re.search(RE_SECT_NAMED_FROM_TO, log_line)
            sect_anonymous_from_to = \
                re.search(RE_SECT_ANON_FROM_TO, log_line)
            sect_anonymous_from_to_short = \
                re.search(RE_SECT_ANON_FROM_TO_SHORT, log_line)
            sect_named_define_negative = \
                re.search(RE_SECT_NEGATIVE_FROM, log_line)

            sect_named_stop = \
                re.search(RE_SECT_NAMED_STOP, log_line)
            sect_anonymous_stop = \
                re.search(RE_SECT_ANON_STOP, log_line)

            if sect_named_from_to:
                current_section = \
                    sect_named_from_to.group(2), \
                    sect_named_from_to.group(3)

            elif sect_anonymous_from_to:
                current_section = \
                    sect_anonymous_from_to.group(1), \
                    sect_anonymous_from_to.group(2)

            elif sect_anonymous_from_to_short:
                current_section = \
                    sect_anonymous_from_to_short.group(1), \
                    sect_anonymous_from_to_short.group(2)

            elif sect_named_define_negative:
                # Ignore, syntax doesn't contain opposite node
                continue

            elif sect_named_stop:
                current_section = None, None

            elif sect_anonymous_stop:
                current_section = None, None

            elif current_section[0] is not None and \
                    current_section[1] is not None:
                sect_measurement = re.search(RE_SECT_MEASUREMENT, log_line)
                if sect_measurement:
                    measurement_bt_addr = sect_measurement.group(3)
                    measurement_dbm = sect_measurement.group(4)
                    measurements.append(
                        (sect_measurement.group(1), current_section[0],
                         current_section[1], measurement_bt_addr,
                         measurement_dbm))

    return measurements


# ------ [ Main Program ] -----------------------------------------------------


def run_parse_file(file_list: List[str]) -> None:
    """Run program to read file.

    :param file_list: The list of files to read.
    :return: Nothing
    """
    measurements_header = \
        ("Localtime", "From", "To", "Bluetooth Address", "dBm")
    total_measurements = []

    for file_path in file_list:
        with open(file_path) as file:
            file_lines = file.readlines()

        monitoring_sections = get_connection_monitoring_sections(file_lines)
        total_measurements += \
            get_connection_monitoring_measurements(monitoring_sections)

    # sorted_measurements = sorted(total_measurements, key=lambda x: x[0])
    # sorted_measurements.insert(0, measurements_header)
    total_measurements.insert(0, measurements_header)

    for measurement_row in total_measurements:
        print(f"{measurement_row[0]},{measurement_row[1]},"
              f"{measurement_row[2]},{measurement_row[3]},"
              f"{measurement_row[4]}")


if __name__ == '__main__':
    # Program Execution
    if len(sys.argv) < 2:
        print_program_usage()
        sys.exit(1)

    file_to_read = []
    for file_arg in range(1, len(sys.argv)):
        if not os.path.exists(sys.argv[file_arg]):
            print(f"ArgFile '{sys.argv[file_arg]}' cannot be found.")
            print_program_usage()
            sys.exit(1)
        else:
            file_to_read.append(sys.argv[file_arg])

    run_parse_file(file_to_read)

