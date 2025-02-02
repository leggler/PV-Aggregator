#!/bin/bash

#bash script to automatically setup raspi for PV-Aggregator. Untested

# Exit on error
set -e

# Define variables
USER_NAME="MiniPi"
INSTALL_DIR="/opt/PV-Aggregator"
SERVICE_NAME="pv-aggregator"
GIT_REPO="https://github.com/leggler/PV-Aggregator.git"
PYTHON_ENV_DIR="$INSTALL_DIR/venv"
APP_DIR="$INSTALL_DIR/app"
START_SCRIPT="$INSTALL_DIR/start_server.sh"
SYSTEMD_SERVICE="/etc/systemd/system/$SERVICE_NAME.service"

# Update system
sudo apt update && sudo apt upgrade -y

# Install necessary packages
sudo apt install -y git python3 python3-pip python3-venv dphys-swapfile

# Disable swap to reduce SD card wear
sudo dphys-swapfile swapoff
sudo dphys-swapfile uninstall
sudo systemctl disable dphys-swapfile

# Create installation directories
sudo mkdir -p $INSTALL_DIR
sudo chown $USER_NAME:$USER_NAME $INSTALL_DIR

# Set up Python virtual environment
python3 -m venv $PYTHON_ENV_DIR
source $PYTHON_ENV_DIR/bin/activate

# Clone the application repository
if [ ! -d "$APP_DIR" ]; then
    git clone $GIT_REPO $APP_DIR
else
    echo "Repository already cloned. Skipping."
fi

# Install application dependencies
pip install -r $APP_DIR/requirements.txt

# Create start script
cat << EOF > $START_SCRIPT
#!/bin/bash
source $PYTHON_ENV_DIR/bin/activate
cd $APP_DIR
python3 Huawei_modubs_UpdateAndServe_Multiparameter.py
EOF

# Make start script executable
chmod +x $START_SCRIPT

# Create systemd service
cat << EOF | sudo tee $SYSTEMD_SERVICE
[Unit]
Description=PV Aggregator Server
After=network.target

[Service]
ExecStart=$START_SCRIPT
WorkingDirectory=$APP_DIR
User=$USER_NAME
Group=$USER_NAME
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable the service
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl start $SERVICE_NAME

# Verify the service is running
sudo systemctl status $SERVICE_NAME

# Optional: Enable read-only mode to reduce SD writes
sudo raspi-config nonint do_overlayfs 1

echo "Installation complete. The PV Aggregator server is running and will start on boot."
