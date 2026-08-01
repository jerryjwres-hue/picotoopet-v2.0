#!/bin/bash
# Picotoo Pet V2 API 端口检测函数；仅检查监听状态，不修改或终止其他进程。

PICOTOO_LSOF_BIN="${PICOTOO_LSOF_BIN:-/usr/sbin/lsof}"

port_is_free() {
  local port="$1"

  if "${PICOTOO_LSOF_BIN}" -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

select_api_port() {
  local candidate

  for candidate in "$@"; do
    if port_is_free "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}
