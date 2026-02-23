#!/usr/bin/env bash
set -euo pipefail

echo "using jetson Jtag skill"

if lsusb | grep -qE 'ID[[:space:]]+0955:7523\b'; then
  echo "Jetson APX recovery USB detected (ID 0955:7523 NVIDIA Corp. APX)"
  exit 0
fi

echo "there is no jetson device is detected ...check if device is in recovery mode"
exit 2
