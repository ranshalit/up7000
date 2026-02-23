#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PRECHECK_SCRIPT="${ROOT_DIR}/.github/skills/jtag-jetson/scripts/check_jetson_jtag_prereq.sh"
HADRON_BACKUP_SCRIPT="${ROOT_DIR}/hadron/backup_and_restore.sh"

usage() {
  cat <<'EOF'
Usage:
  .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh backup <device> <image_prefix>
  .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh restore <device> <image_prefix> --yes-i-know-destructive
  .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh backup-extra <device> <image_prefix>
  .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh restore-extra <device> <image_prefix> --yes-i-know-destructive

Examples:
  .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh backup /dev/sda /tmp/hadron_img
  .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh restore /dev/sda /tmp/hadron_img --yes-i-know-destructive

Notes:
  - Always runs JTAG/APX USB precheck first.
  - restore / restore-extra are destructive and require --yes-i-know-destructive.
  - This wrapper delegates the actual image work to hadron/backup_and_restore.sh.
EOF
}

if [[ ! -x "${PRECHECK_SCRIPT}" ]]; then
  echo "Missing precheck script: ${PRECHECK_SCRIPT}"
  exit 1
fi

if [[ ! -x "${HADRON_BACKUP_SCRIPT}" ]]; then
  echo "Missing backup/restore helper: ${HADRON_BACKUP_SCRIPT}"
  echo "Run: chmod +x hadron/backup_and_restore.sh"
  exit 1
fi

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

ACTION="$1"
shift

case "${ACTION}" in
  backup|restore|backup-extra|restore-extra)
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "Unsupported action: ${ACTION}"
    usage
    exit 1
    ;;
esac

if [[ $# -lt 2 ]]; then
  echo "Missing required args: <device> <image_prefix>"
  usage
  exit 1
fi

DEVICE="$1"
IMAGE_PREFIX="$2"
shift 2

CONFIRM_FLAG=""
if [[ $# -gt 0 ]]; then
  CONFIRM_FLAG="$1"
fi

"${PRECHECK_SCRIPT}"

case "${ACTION}" in
  backup)
    echo "Running backup via hadron helper..."
    exec sudo "${HADRON_BACKUP_SCRIPT}" --backup "${DEVICE}" "${IMAGE_PREFIX}"
    ;;
  backup-extra)
    echo "Running backup-extra via hadron helper..."
    exec sudo "${HADRON_BACKUP_SCRIPT}" --backup "${DEVICE}" "${IMAGE_PREFIX}" --extra
    ;;
  restore|restore-extra)
    if [[ "${CONFIRM_FLAG}" != "--yes-i-know-destructive" ]]; then
      echo "restore is destructive. Re-run with --yes-i-know-destructive"
      exit 3
    fi

    if [[ "${ACTION}" == "restore" ]]; then
      echo "Running restore via hadron helper..."
      exec sudo "${HADRON_BACKUP_SCRIPT}" --restore "${DEVICE}" "${IMAGE_PREFIX}"
    else
      echo "Running restore-extra via hadron helper..."
      exec sudo "${HADRON_BACKUP_SCRIPT}" --restore "${DEVICE}" "${IMAGE_PREFIX}" --extra
    fi
    ;;
esac
