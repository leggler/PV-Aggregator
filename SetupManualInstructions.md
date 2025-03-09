# **Step-by-Step Manual: Setting up Raspberry Pi Zero 2W for PV Aggregator**

## **1. Flash Raspberry Pi OS Lite onto SD Card**
1. **Download Raspberry Pi Imager** from [here](https://www.raspberrypi.com/software/).
2. Insert a **microSD card** (at least 8GB) into your computer.
3. Open **Raspberry Pi Imager** and select:
   - **OS:** Raspberry Pi OS Lite (32-bit)
   - **Storage:** Select your microSD card
4. Click on **⚙️ (Advanced options)**:
   - **Set hostname:** `MiniPi`
   - **Enable SSH** (use password authentication)
   - **Set username and password**:
     - **User:** `MiniPi`
     - **Password:** `XXX` (replace with your password)
   - **Configure Wi-Fi** (optional)
5. Click **WRITE** and wait for the process to complete.

---

## **2. Boot Up the Raspberry Pi**
1. Insert the SD card into the Raspberry Pi Zero 2W.
2. Power it up and connect via **SSH**:
   ```bash
   ssh MiniPi@<your_pi_ip>
   ```
   *(Replace `<your_pi_ip>` with the actual IP of your Raspberry Pi.)*

3. **Update the System:**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

---

## **3. Set a Fixed IP Address for the Server**

If the Raspberry Pi is connected via **RJ45 (Ethernet cable)**, setting a fixed IP address ensures a stable network connection. 

### **Step 1: Identify the Network Interface Name**
Run the following command to list network interfaces:

```bash
ip a
```

Look for an interface like `eth0` (this is usually the Ethernet adapter name).

### **Step 2: Edit the DHCP Configuration**
Open the DHCP configuration file:

```bash
sudo nano /etc/dhcpcd.conf
```

### **Step 3: Set a Static IP Address**
Scroll to the end of the file and add:

```bash
interface eth0
static ip_address=x.x.x.x/24
static routers=y.y.y.y
static domain_name_servers=z.z.z.z
```

- Replace `x.x.x.x` with your **desired static IP** (e.g., `192.168.1.100`).
- Replace `y.y.y.y` with your **router's gateway** (e.g., `192.168.1.1`).
- Replace `z.z.z.z` with your **DNS server** (e.g., `8.8.8.8` for Google DNS).

**Example:**

```bash
interface eth0
static ip_address=192.168.1.100/24
static routers=192.168.1.1
static domain_name_servers=8.8.8.8 1.1.1.1
```

### **Step 4: Save and Apply Changes**
Save and exit (`CTRL+X`, `Y`, `ENTER`).
Restart the network service:

```bash
sudo systemctl restart dhcpcd
```

Or reboot:

```bash
sudo reboot
```

### **Step 5: Verify the Static IP**
Check if the static IP is assigned:

```bash
ip a | grep eth0
```

### **Step 6: Test Network Connectivity**
Test if the Raspberry Pi can reach the internet:

```bash
ping -c 4 8.8.8.8
```

If you get responses, your static IP setup is correct.

---


## **5. Install Required Dependencies**
Run:

```bash
sudo apt install -y git python3 python3-pip python3-venv
```

Verify that `git` is installed correctly:

```bash
git --version
```

---

## **4. Set Up the Python Environment (`PV-Aggregator`)**

### **Folder Structure Overview**
We use `/opt/PV-Aggregator/` as the base directory for the application because `/opt/` is a common location for self-contained, third-party applications on Linux systems. This ensures that the project remains separate from system files and other installed packages.

- `/opt/PV-Aggregator/venv/` → Stores the **Python virtual environment**, isolating dependencies from system-wide Python packages.
- `/opt/PV-Aggregator/app/` → Holds the **application source code**, making it easy to manage and update without affecting the environment.
- `/opt/PV-Aggregator/start_server.sh` → The **startup script** that runs the server inside the virtual environment.

This setup keeps the application self-contained, easy to update, and avoids dependency conflicts with system packages.
Create a **dedicated Python virtual environment**:

```bash
mkdir -p /opt/PV-Aggregator
sudo chown MiniPi:MiniPi /opt/PV-Aggregator
python3 -m venv /opt/PV-Aggregator/venv
```

Activate it:

```bash
source /opt/PV-Aggregator/venv/bin/activate
```

---

## **5. Clone the Server Application from GitHub**
Navigate to the project directory and clone the repository:

```bash
cd /opt/PV-Aggregator
git clone https://github.com/leggler/PV-Aggregator.git app
```

Check if the repository was cloned correctly:

```bash
ls /opt/PV-Aggregator/app
```

install dependencies from `requirements.txt`:
sun2000-modbus==2.2.0
pymodbus==2.5.3

```bash
pip install -r /opt/PV-Aggregator/app/requirements.txt
```

---

## **6. Create an Autostart Script**
Create a **startup script**:

```bash
nano /opt/PV-Aggregator/start_server.sh
```

Add the following content:

```bash
#!/bin/bash
source /opt/PV-Aggregator/venv/bin/activate
cd /opt/PV-Aggregator/app
python3 Huawei_modubs_UpdateAndServe_Multiparameter.py
```


Save and exit (`CTRL+X`, `Y`, `ENTER`).

Make it executable:

```bash
chmod +x /opt/PV-Aggregator/start_server.sh
```
(to see the if it worked run ls -l /opt/PV-Aggregator/start_server.sh)
---

## **7. Create a Systemd Service for Autostart**
Create a **systemd service**:

```bash
sudo nano /etc/systemd/system/pv-aggregator.service
```

Paste this configuration:

```
[Unit]
Description=PV Aggregator Server
After=network.target

[Service]
ExecStart=/opt/PV-Aggregator/start_server.sh
WorkingDirectory=/opt/PV-Aggregator/app
User=MiniPi
Group=MiniPi
Restart=always

[Install]
WantedBy=multi-user.target
```

Save and exit (`CTRL+X`, `Y`, `ENTER`).

---

## **8. Enable and Start the Service**
Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable the service so it starts on boot:

```bash
sudo systemctl enable pv-aggregator.service
```

Start the service:

```bash
sudo systemctl start pv-aggregator.service
```

---

## **9. Verify the Service is Running**
Check the service status:

```bash
sudo systemctl status pv-aggregator.service
```

If the service isn’t running, check logs:

```bash
journalctl -u pv-aggregator.service -f
```

---

## **10. Reboot and Test Autostart**
Reboot your Raspberry Pi:

```bash
sudo reboot
```

After it boots up, check if the server is running:

```bash
sudo systemctl status pv-aggregator.service
```

If everything works, your PV Aggregator server will now start automatically after a reboot or power failure.

---

## **11. Optional: Update Application Code Automatically NOT RECOMENDED**
To pull the latest changes from GitHub on boot, modify **`start_server.sh`**:

```bash
#!/bin/bash
source /opt/PV-Aggregator/venv/bin/activate
cd /opt/PV-Aggregator/app
git pull origin main
python3 main.py
```

This ensures that the latest version is used every time the Raspberry Pi starts.

---

## **12. REDUCE SD-CARD WRITES; TEMPORAL LOGGING**

To further reduce SD card writes and extend its lifespan, we will first setup temporal loggin in ram, and than activate the read-only mod
this means that logs will be lost if server shuts-down.


### **Step 3: Ensure Logging Works in RAM**

```bash
sudo mkdir -p /tmp/logs
```

open config file: 
```bash
sudo nano /etc/fstab
```

add line to config file:
```bash
tmpfs   /tmp/logs   tmpfs   defaults,noatime,nosuid,size=10m   0   0
```

```bash
tmpfs   /tmp/logs   tmpfs   defaults,noatime,nosuid,size=10m   0   0

```
This allows logs to persist during runtime but they will be cleared after a reboot.



### **Step x: Enable Read-Only Mode**
Run:
```bash
sudo raspi-config
```
- Go to **"Performance Options"** → **"Overlay File System"**.
- Enable **read-only mode**.
- Select **"Yes"** to apply changes.

### **Step 2: Reboot**
```bash
sudo reboot
```
After rebooting, the Raspberry Pi will operate in read-only mode, preventing most write operations to the SD card.


### **Step 4: Temporarily Disable Read-Only Mode for Updates**
If you need to make system updates or install new software:
1. **Disable read-only mode**:
   ```bash
   sudo raspi-config
   ```
   - Go to **"Overlay File System"** → Disable it.
2. **Make necessary changes (install, update, etc.)**.
3. **Re-enable read-only mode** when done.

---


## **13. Updating PV-Aggregator Later**
If you need to update **PV-Aggregator**, run:

```bash
cd /opt/PV-Aggregator/app
git pull origin main
sudo systemctl restart pv-aggregator
```

in case you need to also update the venv to new requirements.txt:

navigate to app folder and activate VENV
```bash
cd /opt/PV-Aggregator/app
source /opt/PV-Aggregator/venv/bin/activate
```

Install libraries from requirements.txt

'''bash
pip install -r /opt/PV-Aggregator/app/requirements.txt
'''



## **14. Monitor PV-Aggregator and Raspberry Pi**
Once the service is running, you can monitor its status and the overall Raspberry Pi system using these handy commands:

### **Check the Status of the PV-Aggregator Service**
```bash
sudo systemctl status pv-aggregator
```

### **View Live Logs of the PV-Aggregator Service**
```bash
journalctl -u pv-aggregator -f
```


### **View Live Logs of the PV-Aggregator Service**
```bash
cd /tmp/logs
read log file which is max 5MB, rolling...
```


### **Check the Last 50 Log Entries for PV-Aggregator**
```bash
journalctl -u pv-aggregator -n 50 --no-pager
```

### **Check System-Wide Logs**
```bash
sudo dmesg | tail -20
```

### **Monitor CPU, Memory, and Disk Usage in Real-Time**
```bash
top
```
(Press `q` to exit.)

### **View Available Disk Space**
```bash
df -h
```

### **Monitor Network Activity**
```bash
ifconfig
```

### **Check Temperature and CPU Load**
```bash
vcgencmd measure_temp
uptime
```

### **Redad logs (if setup temporary)**
```bash
nano /tmp/logs/solar_power_aggregator.log
```


