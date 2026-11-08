#!/bin/sh
# PicotooPet P0 #237: READ-ONLY Mac SSH/Core discovery.
# Scope              : local metadata only; no network, sudo, write, SSH login or secret access.
# Result             : informational facts, never transport acceptance.
# Execution          : only after the Mac owner explicitly approves the device check.

set -u
LC_ALL=C
export LC_ALL

emit() {
    printf '%s=%s\n' "$1" "$2"
}

listener_observed() {
    # This shows socket presence only; it does not prove which service owns it.
    if ! command -v lsof >/dev/null 2>&1; then
        emit "$2" "UNVERIFIED_LSOF_UNAVAILABLE"
    elif lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | grep -q .; then
        emit "$2" "OBSERVED_UNATTRIBUTED"
    else
        emit "$2" "NOT_OBSERVED_NOT_PROOF_OF_DISABLEMENT"
    fi
}

emit "CHECK_SCHEMA" "owner_ssh_readonly_preflight.v1"
emit "DEVICE_ROLE" "MAC"
emit "DEVICE_ACTIONS" "READ_ONLY_NO_NETWORK_NO_SUDO"
emit "SOURCE_DEFAULT_CORE_API_PORT" "8765"

# macOS Remote Login may be activated on demand. An open port is only a hint.
listener_observed "22" "MAC_SSH_22_LISTENER"
listener_observed "8765" "MAC_CORE_8765_LISTENER"
listener_observed "8766" "MAC_CORE_8766_LISTENER"

# launchctl disabled state is an OS hint; it is not a successful SSH handshake.
if command -v launchctl >/dev/null 2>&1; then
    sshd_state="$(launchctl print-disabled system 2>/dev/null |
        grep 'com.openssh.sshd' | head -n 1 || true)"
    case "$sshd_state" in
        *'=> disabled'*) emit "MAC_REMOTE_LOGIN_POLICY" "DISABLED_REPORTED" ;;
        *'=> enabled'*)  emit "MAC_REMOTE_LOGIN_POLICY" "ENABLED_REPORTED_NOT_CONNECTIVITY" ;;
        *)             emit "MAC_REMOTE_LOGIN_POLICY" "UNVERIFIED" ;;
    esac
else
    emit "MAC_REMOTE_LOGIN_POLICY" "UNVERIFIED"
fi

# Fingerprint only from Mac's PUBLIC host key, never from a private key or network.
public_key="/etc/ssh/ssh_host_ed25519_key.pub"
if [ -r "$public_key" ] && command -v ssh-keygen >/dev/null 2>&1; then
    key_info="$(ssh-keygen -lf "$public_key" -E sha256 2>/dev/null || true)"
    case "$key_info" in
        *' SHA256:'*' (ED25519)'*)
            fingerprint="$(printf '%s\n' "$key_info" |
                awk '{for (i=1; i<=NF; i++) if ($i ~ /^SHA256:/) print $i}')"
            if [ -n "$fingerprint" ]; then
                emit "MAC_SSH_ED25519_HOST_FP" "$fingerprint"
            else
                emit "MAC_SSH_ED25519_HOST_FP" "UNVERIFIED"
            fi ;;
        *) emit "MAC_SSH_ED25519_HOST_FP" "UNVERIFIED" ;;
    esac
else
    emit "MAC_SSH_ED25519_HOST_FP" "UNVERIFIED_KEY_NOT_READABLE"
fi

# No bearer, account name, private key, IP address or source evidence leaves this check.
emit "MAC_RUNTIME_CORE_IDENTITY" "UNVERIFIED_REQUIRES_AUTHENTICATED_READ_ONLY_CHECK"
emit "MAC_SSH_AUTHENTICATED_HANDSHAKE" "NOT_PERFORMED"
emit "MAC_OWNER_REVIEW_LIVE_READY" "BLOCKED"
