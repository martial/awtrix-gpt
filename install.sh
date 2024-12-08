#!/bin/bash

# Variables
APP_DIR="/home/martial/awtrix-gpt"  # Updated path for your setup
SERVICE_NAME="awtrix.service"
PYTHON_BIN="/usr/bin/python3"  # Adjust if needed

# Step 1: Create a Python virtual environment
echo "Creating Python virtual environment..."
cd "$APP_DIR" || exit
$PYTHON_BIN -m venv venv

# Step 2: Install requirements in the virtual environment
echo "Installing requirements..."
$APP_DIR/venv/bin/pip install -r requirements.txt --break-system-packages

# Step 3: Create a systemd service
echo "Creating systemd service..."
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
sudo bash -c "cat > $SERVICE_PATH" << EOL
[Unit]
Description=AWTRIX App
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/flask_server.py
Restart=always
User=martial

[Install]
WantedBy=multi-user.target
EOL

# Step 4: Enable and start the service
echo "Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl start $SERVICE_NAME

echo "Setup complete! The server should now start at boot."
