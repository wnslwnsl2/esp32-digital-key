# WSL2 USB passthrough - run as Administrator
# Intel Wireless Bluetooth (BUSID 2-14)
# ESP32-S3 USB JTAG/serial (BUSID 3-1)
#
# Usage:
#   .\wsl-bluetooth.ps1           # Attach all to WSL
#   .\wsl-bluetooth.ps1 -Detach   # Return all to Windows

param(
    [switch]$Detach
)

if ($Detach) {
    Write-Host "Detaching devices from WSL..."
    usbipd detach --busid 2-14
    usbipd detach --busid 3-1
    Write-Host "Done. Devices returned to Windows."
} else {
    # Bluetooth
    Write-Host "Attaching Bluetooth to WSL..."
    usbipd bind --busid 2-14
    usbipd attach --wsl --busid 2-14

    # ESP32
    Write-Host "Attaching ESP32 to WSL..."
    usbipd bind --busid 3-1
    usbipd attach --wsl --busid 3-1

    # Start BlueZ
    Write-Host "Starting BlueZ in WSL..."
    wsl -u root service bluetooth start
    wsl bluetoothctl show
    Write-Host ""
    Write-Host "=== Connected BLE devices ==="
    wsl bluetoothctl devices Connected
    Write-Host ""
    Write-Host "Done. ESP32 available at /dev/ttyACM0 or /dev/ttyUSB0"
}
