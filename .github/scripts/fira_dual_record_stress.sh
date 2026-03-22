#!/usr/bin/env bash
set -u

iterations="${1:-10}"
capture_dir="$HOME/Camera_test/video"
camera_script="$HOME/camera.py"
log_root="/tmp/fira_dual_record_logs"
summary_file="/tmp/fira_dual_record_summary.txt"
cam_a=2
cam_b=0
python_bin="${PYTHON_BIN:-$(command -v python3 || command -v python || true)}"

mkdir -p "$capture_dir" "$log_root"
: > "$summary_file"

if [[ -z "$python_bin" ]]; then
  echo "No python interpreter found on target" >&2
  exit 1
fi

cleanup_iteration() {
  if [[ -n "${writer_a_fd:-}" ]]; then
    eval "exec ${writer_a_fd}>&-" || true
    unset writer_a_fd
  fi
  if [[ -n "${writer_b_fd:-}" ]]; then
    eval "exec ${writer_b_fd}>&-" || true
    unset writer_b_fd
  fi
  [[ -n "${pipe_a:-}" ]] && rm -f "$pipe_a"
  [[ -n "${pipe_b:-}" ]] && rm -f "$pipe_b"
  if [[ -n "${pid_a:-}" ]] && kill -0 "$pid_a" 2>/dev/null; then
    kill "$pid_a" 2>/dev/null || true
    wait "$pid_a" 2>/dev/null || true
  fi
  if [[ -n "${pid_b:-}" ]] && kill -0 "$pid_b" 2>/dev/null; then
    kill "$pid_b" 2>/dev/null || true
    wait "$pid_b" 2>/dev/null || true
  fi
  unset pid_a pid_b pipe_a pipe_b log_a log_b
}

cleanup_all() {
  cleanup_iteration
}

trap cleanup_all EXIT

wait_for_ready() {
  local attempts=0
  while (( attempts < 20 )); do
    if ! kill -0 "$pid_a" 2>/dev/null || ! kill -0 "$pid_b" 2>/dev/null; then
      return 1
    fi
    if grep -q "Using /dev/video" "$log_a" 2>/dev/null && grep -q "Using /dev/video" "$log_b" 2>/dev/null; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done
  return 1
}

record_iteration() {
  local index="$1"
  local dir_count=0
  local nonempty_count=0
  local status="PASS"

  echo "[iter ${index}] clearing $capture_dir"
  find "$capture_dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true

  pipe_a="/tmp/fira_cam_${cam_a}_${index}.fifo"
  pipe_b="/tmp/fira_cam_${cam_b}_${index}.fifo"
  log_a="$log_root/cam_${cam_a}_iter_${index}.log"
  log_b="$log_root/cam_${cam_b}_iter_${index}.log"

  rm -f "$pipe_a" "$pipe_b"
  mkfifo "$pipe_a" "$pipe_b"

  "$python_bin" "$camera_script" fira --camera-id "$cam_a" --headless <"$pipe_a" >"$log_a" 2>&1 &
  pid_a=$!
  "$python_bin" "$camera_script" fira --camera-id "$cam_b" --headless <"$pipe_b" >"$log_b" 2>&1 &
  pid_b=$!

  exec {writer_a_fd}>"$pipe_a"
  exec {writer_b_fd}>"$pipe_b"

  if ! wait_for_ready; then
    status="FAIL:start"
  else
    printf 'v\n' >&${writer_a_fd}
    printf 'v\n' >&${writer_b_fd}
    sleep 5
    printf 'v\n' >&${writer_a_fd}
    printf 'v\n' >&${writer_b_fd}
    sleep 1
    printf 'esc\n' >&${writer_a_fd}
    printf 'esc\n' >&${writer_b_fd}
    wait "$pid_a"
    wait "$pid_b"

    dir_count=$(find "$capture_dir" -mindepth 1 -maxdepth 1 -type d | wc -l)
    while IFS= read -r dir_path; do
      [[ -z "$dir_path" ]] && continue
      if find "$dir_path" -mindepth 1 -type f | read -r _; then
        nonempty_count=$((nonempty_count + 1))
      fi
    done < <(find "$capture_dir" -mindepth 1 -maxdepth 1 -type d | sort)

    if [[ "$dir_count" -ne 2 || "$nonempty_count" -ne 2 ]]; then
      status="FAIL:outputs"
    fi
  fi

  printf '[iter %s] status=%s dir_count=%s nonempty_dirs=%s\n' "$index" "$status" "$dir_count" "$nonempty_count" | tee -a "$summary_file"
  if [[ "$status" != "PASS" ]]; then
    echo "[iter ${index}] tail cam ${cam_a} log"
    tail -n 40 "$log_a" 2>/dev/null || true
    echo "[iter ${index}] tail cam ${cam_b} log"
    tail -n 40 "$log_b" 2>/dev/null || true
  fi

  cleanup_iteration

  [[ "$status" == "PASS" ]]
}

pass_count=0
for ((i = 1; i <= iterations; i++)); do
  if record_iteration "$i"; then
    pass_count=$((pass_count + 1))
  fi
done

echo "[summary] passes=${pass_count}/${iterations}"
cat "$summary_file"
if [[ "$pass_count" -ne "$iterations" ]]; then
  exit 1
fi
