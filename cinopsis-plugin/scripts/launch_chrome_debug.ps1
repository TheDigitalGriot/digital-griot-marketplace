# launch_chrome_debug.ps1 - the ONE-TIME fix for the Chrome profile-lock
# problem documented in scripts/chrome_session.py.
#
# Chromium cannot turn on remote debugging for an already-running Chrome
# process - the --remote-debugging-port flag only takes effect at launch, on
# every OS. So if Gavin's Chrome GB (Profile 1) is already open WITHOUT that
# flag, cinopsis's panel rungs can neither attach to it (nothing is
# listening) nor launch a second process against the same profile (Chrome's
# singleton lock refuses it) - the exact crash the yt-ladder-fix contract
# names (chromedriver GetHandleVerifier, exit 1).
#
# Run this ONCE - or replace Gavin's normal Chrome shortcut with a copy of
# this command - and every later cinopsis run ATTACHES to the already-open
# debug port instead of trying (and failing) to launch its own. This does
# NOT open a second Chrome: if Profile 1 is already running with the port
# open, this script's own probe below just confirms it and exits.
#
# Usage:  powershell -File scripts\launch_chrome_debug.ps1

$ErrorActionPreference = "Stop"

$Port = if ($env:CINOPSIS_PANEL_CDP_PORT) { $env:CINOPSIS_PANEL_CDP_PORT } else { "9333" }
$UserDataDir = if ($env:CINOPSIS_CHROME_USER_DATA) { $env:CINOPSIS_CHROME_USER_DATA } else { "$env:LOCALAPPDATA\Google\Chrome\User Data" }
$ProfileDir = if ($env:CINOPSIS_CHROME_PROFILE) { $env:CINOPSIS_CHROME_PROFILE } else { "Profile 1" }

try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 -UseBasicParsing
    Write-Host "Chrome is already listening on port $Port - nothing to do. Cinopsis will attach to it."
    exit 0
} catch {
    # Not listening yet - fall through and launch it.
}

$ChromeExe = "${env:PROGRAMFILES}\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $ChromeExe)) {
    $ChromeExe = "${env:LOCALAPPDATA}\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $ChromeExe)) {
    Write-Error "Chrome not found. Set `$env:CINOPSIS_CHROME to the chrome.exe path and re-run."
    exit 1
}

Write-Host "Launching Chrome on '$ProfileDir' with debug port $Port..."
Start-Process -FilePath $ChromeExe -ArgumentList @(
    "--user-data-dir=$UserDataDir",
    "--profile-directory=$ProfileDir",
    "--remote-debugging-port=$Port",
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-default-browser-check"
)

Write-Host "Done. From now on, cinopsis panel rungs will ATTACH to this window - use it as your normal browser."
