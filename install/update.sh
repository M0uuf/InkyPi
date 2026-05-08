#!/bin/bash

# Formatting stuff
bold=$(tput bold)
normal=$(tput sgr0)
green=$(tput setaf 2)
red=$(tput setaf 1)

SOURCE=${BASH_SOURCE[0]}
while [ -h "$SOURCE" ]; do # resolve $SOURCE until the file is no longer a symlink
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE=$DIR/$SOURCE
done
SCRIPT_DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

APPNAME="inkypi"
INSTALL_PATH="/usr/local/$APPNAME"
SRC_PATH="$SCRIPT_DIR/../src"
BINPATH="/usr/local/bin"
VENV_PATH="$INSTALL_PATH/venv_$APPNAME"

SERVICE_FILE="$APPNAME.service"
SERVICE_FILE_SOURCE="$SCRIPT_DIR/$SERVICE_FILE"
SERVICE_FILE_TARGET="/etc/systemd/system/$SERVICE_FILE"

APT_REQUIREMENTS_FILE="$SCRIPT_DIR/debian-requirements.txt"
PIP_REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
WS_REQUIREMENTS_FILE="$SCRIPT_DIR/ws-requirements.txt"
WS_TYPE=""

echo_success() {
  echo -e "$1 [\e[32m\xE2\x9C\x94\e[0m]"
}

echo_error() {
  echo -e "$1 [\e[31m\xE2\x9C\x98\e[0m]\n"
}

parse_arguments() {
  while getopts ":W:" opt; do
    case $opt in
      W) WS_TYPE=$OPTARG
          echo "Waveshare display type set from -W: $WS_TYPE"
          ;;
      \?) echo "Invalid option: -$OPTARG." >&2
          exit 1
          ;;
      :) echo "Option -$OPTARG requires the model type of the Waveshare screen." >&2
         exit 1
         ;;
    esac
  done
}

resolve_waveshare_type() {
  local DEVICE_JSON="$SRC_PATH/config/device.json"

  if [[ -z "$WS_TYPE" && -f "$DEVICE_JSON" ]]; then
    WS_TYPE=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1])).get('display_type', ''))" "$DEVICE_JSON")
  fi

  if [[ -z "$WS_TYPE" || ! "$WS_TYPE" =~ ^epd[0-9]+(in[0-9]+)?[A-Za-z0-9_]*$ ]]; then
    echo_error "ERROR: A Waveshare display_type is required for update. Set src/config/device.json display_type to a Waveshare model or rerun update with -W <waveshare_model>, e.g. -W epd7in3f."
    exit 1
  fi

  echo "Using Waveshare display type: $WS_TYPE"
}

update_config() {
  local DEVICE_JSON="$SRC_PATH/config/device.json"

  if [ ! -f "$DEVICE_JSON" ]; then
    echo_error "ERROR: Device config not found at $DEVICE_JSON. Run the installation script first."
    exit 1
  fi

  python3 -c "import json, sys; path, display_type = sys.argv[1], sys.argv[2]; data = json.load(open(path)); data['display_type'] = display_type; open(path, 'w').write(json.dumps(data, indent=4) + '\n')" "$DEVICE_JSON" "$WS_TYPE"
  echo_success "Updated display_type to: $WS_TYPE"
}

fetch_waveshare_driver() {
  echo "Fetching Waveshare driver for: $WS_TYPE"

  DRIVER_DEST="$SRC_PATH/display/waveshare_epd"
  DRIVER_FILE="$DRIVER_DEST/$WS_TYPE.py"
  DRIVER_URL="https://raw.githubusercontent.com/waveshareteam/e-Paper/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd/$WS_TYPE.py"

  if [ -f "$DRIVER_FILE" ]; then
    echo_success "Waveshare driver '$WS_TYPE.py' already exists at $DRIVER_FILE"
  elif curl --silent --fail -o "$DRIVER_FILE" "$DRIVER_URL"; then
    echo_success "Waveshare driver '$WS_TYPE.py' successfully downloaded to $DRIVER_FILE"
  else
    echo_error "ERROR: Failed to download Waveshare driver '$WS_TYPE.py'. Ensure the model name is correct."
    exit 1
  fi

  EPD_CONFIG_FILE="$DRIVER_DEST/epdconfig.py"
  EPD_CONFIG_URL="https://raw.githubusercontent.com/waveshareteam/e-Paper/refs/heads/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epdconfig.py"
  if [ -f "$EPD_CONFIG_FILE" ]; then
    echo_success "Waveshare epdconfig file already exists at $EPD_CONFIG_FILE"
  elif curl --silent --fail -o "$EPD_CONFIG_FILE" "$EPD_CONFIG_URL"; then
    echo_success "Waveshare epdconfig file successfully downloaded to $EPD_CONFIG_FILE"
  else
    echo_error "ERROR: Failed to download Waveshare epdconfig file."
    exit 1
  fi
}

setup_zramswap_service() {
  echo "Enabling and starting zramswap service."
  sudo apt-get install -y zram-tools > /dev/null
  echo -e "ALGO=zstd\nPERCENT=60" | sudo tee /etc/default/zramswap > /dev/null
  sudo systemctl enable --now zramswap
}

setup_earlyoom_service() {
  echo "Enabling and starting earlyoom service."
  sudo apt-get install -y earlyoom > /dev/null
  sudo systemctl enable --now earlyoom
}

update_app_service() {
  echo "Updating $APPNAME systemd service."
  if [ -f "$SERVICE_FILE_SOURCE" ]; then
    cp "$SERVICE_FILE_SOURCE" "$SERVICE_FILE_TARGET"
    echo "Restarting $APPNAME service."
    sudo systemctl daemon-reload
    sudo systemctl restart $SERVICE_FILE
  else
    echo_error "ERROR: Service file $SERVICE_FILE_SOURCE not found!"
    exit 1
  fi
}

remove_legacy_cli() {
  if [ -d "$INSTALL_PATH/cli" ]; then
    rm -rf "$INSTALL_PATH/cli"
    echo_success "Removed legacy plugin CLI."
  fi
}

# Get OS release number, e.g. 11=Bullseye, 12=Bookworm, 13=Trixe
get_os_version() {
  echo "$(lsb_release -sr)"
}


parse_arguments "$@"

# Ensure script is run with sudo
if [ "$EUID" -ne 0 ]; then
  echo_error "ERROR: This script requires root privileges. Please run it with sudo."
  exit 1
fi

resolve_waveshare_type
update_config

apt-get update -y > /dev/null &
if [ -f "$APT_REQUIREMENTS_FILE" ]; then
  echo "Installing system dependencies... "
  xargs -a "$APT_REQUIREMENTS_FILE" sudo apt-get install -y > /dev/null && echo_success "Installed system dependencies."
else
  echo_error "ERROR: System dependencies file $APT_REQUIREMENTS_FILE not found!"
  exit 1
fi

fetch_waveshare_driver

# check OS version for Bookworm to setup zramswap
if [[ $(get_os_version) = "12" ]] ; then
  echo "OS version is Bookworm - setting up zramswap"
  setup_zramswap_service
else
  echo "OS version is not Bookworm - skipping zramswap setup."
fi
setup_earlyoom_service

# Check if virtual environment exists
if [ ! -d "$VENV_PATH" ]; then
  echo_error "ERROR: Virtual environment not found at $VENV_PATH. Run the installation script first."
  exit 1
fi

# Activate the virtual environment
source "$VENV_PATH/bin/activate"

# Upgrade pip
echo "Upgrading pip..."
$VENV_PATH/bin/python -m pip install --upgrade pip setuptools wheel > /dev/null && echo_success "Pip upgraded successfully."

# Install or update Python dependencies
if [ -f "$PIP_REQUIREMENTS_FILE" ]; then
  echo "Updating Python dependencies..."
  $VENV_PATH/bin/python -m pip install --upgrade -r "$PIP_REQUIREMENTS_FILE" -qq > /dev/null && echo_success "Dependencies updated successfully."
else
  echo_error "ERROR: Requirements file $PIP_REQUIREMENTS_FILE not found!"
  exit 1
fi

if [ -f "$WS_REQUIREMENTS_FILE" ]; then
  echo "Updating Waveshare Python dependencies..."
  $VENV_PATH/bin/python -m pip install --upgrade -r "$WS_REQUIREMENTS_FILE" -qq > /dev/null && echo_success "Waveshare dependencies updated successfully."
else
  echo_error "ERROR: Waveshare requirements file $WS_REQUIREMENTS_FILE not found!"
  exit 1
fi

if $VENV_PATH/bin/python -m pip show inky > /dev/null 2>&1; then
  echo "Removing obsolete Pimoroni Inky dependency..."
  $VENV_PATH/bin/python -m pip uninstall -y inky > /dev/null && echo_success "Removed obsolete inky package."
fi

for obsolete_package in openai numpy feedparser; do
  if $VENV_PATH/bin/python -m pip show "$obsolete_package" > /dev/null 2>&1; then
    echo "Removing obsolete plugin dependency: $obsolete_package"
    $VENV_PATH/bin/python -m pip uninstall -y "$obsolete_package" > /dev/null && echo_success "Removed obsolete $obsolete_package package."
  fi
done

echo "Updating executable in ${BINPATH}/$APPNAME"
cp $SCRIPT_DIR/inkypi $BINPATH/
sudo chmod +x $BINPATH/$APPNAME

echo "Update JS and CSS files"
bash $SCRIPT_DIR/update_vendors.sh > /dev/null

update_app_service
remove_legacy_cli

echo_success "Update completed."
