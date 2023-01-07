# Bluetooth LE Experiment Project
Contains programs to:
* Connect multiple devices and monitor RSSI.

## Demo
Coming soon.

## Requirements
### Hardware
* 4 x **Raspberry Pi 3 Model B+**, [Find available RPi at rpilocator](https://rpilocator.com/); and
* 4 x **([at least*](https://www.raspberrypi.com/documentation/computers/getting-started.html#recommended-capacity)) 8 GB SD card**, [Browse at prisjakt.nu](https://www.prisjakt.nu/c/sd-kort?r_95336=8-1000); and
* 4 x **Ethernet Cable**; and
* A **computer** to connect to and communicate with the Raspberry Pi 3 Model B+
  * This guide currently supports installation instructions for **Ubuntu 22**

## Good To know
### Official Documentation
* **Bluetooth® Technology for Linux Developers**, [link to download page on bluetooth.com](https://www.bluetooth.com/bluetooth-resources/bluetooth-for-linux/)
* **The Bluetooth® Low Energy Primer**, [link to download page on bluetooth.com](https://www.bluetooth.com/bluetooth-resources/the-bluetooth-low-energy-primer/)

### Clone
Clone the repository
```shell
git clone git@github.com:martenb-se/ik2560-bluetooth-le-experiment.git
```

## Set Up
### Install Raspberry Pi OS on the Raspberry Pi 3 Model B+
1. Download and install the [Raspberry Pi Imager from raspberrypi.com](https://www.raspberrypi.com/software/)
2. Download the image (`2022-09-22-raspios-bullseye-armhf.img.xz`) for [Raspberry Pi OS (32-bit) from 2022-09-22](https://downloads.raspberrypi.org/raspios_armhf/images/)
3. Start the **Raspberry Pi Imager**
   1. Under *Operating System*, select **Use custom** and open the downloaded `2022-09-22-raspios-bullseye-armhf.img.xz`
   2. Under *Storage*, select the **SD card**
   3. Click on the *cog icon* to open *Advanced options*
      1. Check the *"Enable SSH"* option and choose between public-key or password authentication.
   4. Click **Save**
   5. Click **Write** and wait for it to finish.

### (Optional) Share internet from the development computer to the Raspberry Pi 3 Model B+
If only the development computer is able to have internet access, this computer can share its access with the 
Raspberry Pi 3 Model B+.
#### Ubuntu 22
1. Share the computer's internet connection (from Wi-Fi) via ethernet
   1. Open a terminal and enter `nm-connection-editor`.
   2. Add a new connection by pressing the + (plus) sign.
   3. Choose __Ethernet__ and continue by clicking __Create...__
   4. Go to __IPv4 Settings__
   5. Choose "**Shared to other computers**"
   6. Save the connection as "Shared Internet"
2. Connect Raspberry Pi to the computer via ethernet.

Instructions for older versions of Ubuntu: https://help.ubuntu.com/community/Internet/ConnectionSharing

### (Optional) Sync development from the computer to the Raspberry Pi 3 Model B+
1. Install __lsyncd__
   ```shell
   sudo apt update
   sudo apt install lsyncd
   ```
2. Begin syncing project from your __computer__ to the __Raspberry Pi__ (sync project to **pi**'s home dir).
   ```shell
   lsyncd -nodaemon -rsync \
       "<path-to-cloned-repo>/ik2560-bluetooth-le-experiment" \
       "pi@<ip-or-hostname-for-RPi>:/home/pi/ik2560-bluetooth-le-experiment"
   ```
   Simply interrupt (CTRL+C) to stop the sync.

## Running BLE Connect & RSSI Monitoring Program
1. Go to the project folder on the Raspberry Pi
   ```shell
   cd /home/pi/ik2560-bluetooth-le-experiment
   ```
2. Run in one of the following modes:
   1. Run in **automatic** node mode
      ```shell
      python3 main.py
      ```
   2. Run in **central** node mode
      ```shell
      python3 main.py -n central
      ```
   3. Run in **peripheral** node mode
      ```shell
      python3 main.py -n peripheral
      ```

## Running program to parse full log from "BLE Connect & RSSI Monitoring Program"
After having connected two Raspberry Pis and having measured the RSSI, to get named measurements from logged output, 
run the following:
```shell
python3 log_parser.py <Path to log file> [<Path to log file 2> ...]
```

Save output to file with:
```shell
python3 log_parser.py <Path to log file> [<Path to log file 2> ...] > output_file.csv
```

## Running Low Level Bluetooth Testing Programs
Go to the project folder on the Raspberry Pi
```shell
cd /home/pi/ik2560-bluetooth-le-experiment
```

### Install development library on Raspberry Pi 3
```shell
sudo apt update
sudo apt-get install libbluetooth-dev
```

### Compile
Compile all programs with *make* and run:
```shell
make
```

### Raspberry Pi discoverability over Bluetooth
In order for the Raspberry Pi to be visible it must advertise its existence.

#### Check discoverability
To check discoverability, run:
```shell
hciconfig
```

If the output contains `UP RUNNING`, the Raspberry Pi is **not** discoverable! 

However, if it says `UP RUNNING PSCAN ISCAN` 
it **is discoverable**.

#### Make Raspberry Pi visible
If the Raspberry Pi is not visible, then run:
```shell
sudo hciconfig hci0 piscan
```

#### Stop Raspberry Pi from being visible
To make the Raspberry Pi unavailable and invisible, run:
```shell
sudo hciconfig hci0 noscan
```

### Run 
#### Run L2CAP Server
In order to start the L2CAP Server after having made sure the Raspberry Pi is discoverable, then run:
```shell
./build/l2cap-server
```

The method `dev_info` from *hcitool.c* 
([see source code](https://github.com/pauloborges/bluez/blob/master/tools/hcitool.c#L77)) 
is implemented into the program and when the server is  started, the Raspberry Pi's Bluetooth addresses will be 
displayed. This is the address to type where you see `<Bluetooth address to L2CAP server>` in the upcoming command. 
This is the same output you will see if you run the command `hcitool dev` on the Raspberry Pi.

#### Run L2CAP Client
To run and connect the client to the server run:
```shell
./build/l2cap-client <Bluetooth address to RPi running L2CAP server>
```
