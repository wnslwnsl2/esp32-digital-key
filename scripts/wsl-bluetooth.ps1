# WSL2 USB passthrough - run as Administrator
# VID:PID로 장치를 찾으므로 BUSID가 변경되어도 동작합니다.
#
# Usage:
#   .\wsl-bluetooth.ps1           # Attach all to WSL
#   .\wsl-bluetooth.ps1 -Detach   # Return all to Windows

param(
    [switch]$Detach
)

# ── Device VID:PID ──────────────────────────────────────
$devices = @{
    "ESP32"     = "303a:1001"   # USB JTAG/serial debug unit
}

function Find-BusId($hwid) {
    $lines = usbipd list 2>$null
    foreach ($line in $lines) {
        if ($line -match "^\s*(\d+-\d+)\s+$([regex]::Escape($hwid))") {
            return $Matches[1]
        }
    }
    return $null
}

if ($Detach) {
    Write-Host "Detaching devices from WSL..."
    foreach ($name in $devices.Keys) {
        $busid = Find-BusId $devices[$name]
        if ($busid) {
            usbipd detach --busid $busid
            Write-Host "  $name ($($devices[$name])) detached (BUSID $busid)"
        } else {
            Write-Host "  $name ($($devices[$name])) not found, skipping"
        }
    }
    Write-Host "Done. Devices returned to Windows."
} else {
    foreach ($name in $devices.Keys) {
        $hwid = $devices[$name]
        $busid = Find-BusId $hwid
        if (-not $busid) {
            Write-Host "  $name ($hwid) not found, skipping" -ForegroundColor Yellow
            continue
        }
        Write-Host "Attaching $name ($hwid, BUSID $busid) to WSL..."
        usbipd bind --busid $busid 2>$null
        usbipd attach --wsl --busid $busid
    }

    Write-Host ""
    Write-Host "Done. ESP32 available at /dev/ttyACM0 or /dev/ttyUSB0"
}
