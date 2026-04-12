#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Create host-side macvlan shim interfaces for container communication.
#
# Macvlan isolates containers from the host by design. These shim interfaces
# provide a bridge-mode macvlan sub-interface on each parent NIC so the host
# can reach the Traefik VIPs assigned by Docker Swarm.
#
# Idempotent: safe to run multiple times or at every boot.
#
# Persist via systemd (run on prd-srv-edge-01):
#   REPO=/home/alvis/repos/docker-swarm-homelab
#   sudo cp "$REPO/scripts/edge/create_macvlan_shims.sh" /usr/local/bin/
#   sudo cp "$REPO/scripts/edge/macvlan-shims.service" /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable macvlan-shims.service
# ---------------------------------------------------------------------------
set -Eeuo pipefail

create_shim() {
  local name="$1" parent="$2" addr="$3" route="$4"

  if ip link show "${name}" &>/dev/null; then
    local needs_recreate=false

    # Verify link is up
    if ! ip link show "${name}" | grep -q 'state UP'; then
      printf 'MISMATCH: %s is not UP, will recreate\n' "${name}"
      needs_recreate=true
    fi

    # Verify address is assigned
    if ! ip addr show "${name}" | grep -q "${addr}"; then
      printf 'MISMATCH: %s missing addr %s, will recreate\n' "${name}" "${addr}"
      needs_recreate=true
    fi

    # Verify route exists
    if ! ip route show dev "${name}" | grep -q "${route%%/*}"; then
      printf 'MISMATCH: %s missing route %s, will recreate\n' "${name}" "${route}"
      needs_recreate=true
    fi

    if [[ "${needs_recreate}" == false ]]; then
      printf 'OK: shim verified: %s (up, addr %s, route %s)\n' "${name}" "${addr}" "${route}"
      return 0
    fi

    # Tear down before recreating
    ip link del "${name}" 2>/dev/null || true
  fi

  ip link add "${name}" link "${parent}" type macvlan mode bridge
  ip addr add "${addr}" dev "${name}"
  ip link set "${name}" up
  ip route add "${route}" dev "${name}"
  printf 'CREATED: shim %s (addr %s, route %s)\n' "${name}" "${addr}" "${route}"
}

# DMZ shim (VLAN20) — host talks to Traefik VIP 192.168.20.200
create_shim dmzmac0 enp2s0f0np0 192.168.20.244/32 192.168.20.200/32

# LAN shim (VLAN40) — host talks to Traefik VIP 10.10.40.200
create_shim lanmac0 enp2s0f1np1 10.10.40.244/32 10.10.40.200/32

printf '\nVerification:\n'
ip -br addr show dmzmac0
ip -br addr show lanmac0
