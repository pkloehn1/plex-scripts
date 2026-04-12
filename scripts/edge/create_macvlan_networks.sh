#!/usr/bin/env bash
set -Eeuo pipefail

# =============================================================================
# Create Swarm-scope macvlan networks for edge stack dual-homing
# =============================================================================
# Requires: run on prd-srv-edge-01 while it is a Swarm manager (temp promote).
#
# Usage:
#   sudo docker node promote prd-srv-edge-01
#   ssh prd-srv-edge-01
#   sudo ./scripts/edge/create_macvlan_networks.sh
#   sudo docker node demote prd-srv-edge-01   # from control node
# =============================================================================

# --- DMZ macvlan (VLAN20) ---------------------------------------------------
DMZ_CONFIG="dmz_macvlan_config"
DMZ_NETWORK="${DMZ_MACVLAN_NETWORK:-dmz_macvlan}"
DMZ_PARENT="enp2s0f0np0"
DMZ_SUBNET="192.168.20.0/24"
DMZ_GATEWAY="192.168.20.1"
DMZ_IP_RANGE="192.168.20.200/32"
DMZ_AUX="host_vlan20=192.168.20.31"

# --- LAN macvlan (VLAN40) ---------------------------------------------------
LAN_CONFIG="lan_macvlan_config"
LAN_NETWORK="${LAN_MACVLAN_NETWORK:-lan_macvlan}"
LAN_PARENT="enp2s0f1np1"
LAN_SUBNET="10.10.40.0/24"
LAN_GATEWAY="10.10.40.1"
LAN_IP_RANGE="10.10.40.200/32"
LAN_AUX="host_vlan40=10.10.40.31"

create_macvlan() {
  local config_name="$1" network_name="$2" parent="$3"
  local subnet="$4" gateway="$5" ip_range="$6" aux="$7"

  # Config-only (node-local template)
  if docker network inspect "${config_name}" &>/dev/null; then
    printf 'OK: config-only network already exists: %s\n' "${config_name}"
  else
    docker network create --config-only \
      --subnet "${subnet}" \
      --gateway "${gateway}" \
      --ip-range "${ip_range}" \
      --aux-address "${aux}" \
      -o parent="${parent}" \
      "${config_name}"
    printf 'CREATED: config-only network: %s\n' "${config_name}"
  fi

  # Swarm-scope macvlan
  if docker network inspect "${network_name}" &>/dev/null; then
    printf 'OK: swarm macvlan already exists: %s\n' "${network_name}"
  else
    docker network create -d macvlan \
      --scope swarm \
      --config-from "${config_name}" \
      "${network_name}"
    printf 'CREATED: swarm macvlan: %s\n' "${network_name}"
  fi

  return 0
}

create_macvlan "${DMZ_CONFIG}" "${DMZ_NETWORK}" "${DMZ_PARENT}" \
  "${DMZ_SUBNET}" "${DMZ_GATEWAY}" "${DMZ_IP_RANGE}" "${DMZ_AUX}"

create_macvlan "${LAN_CONFIG}" "${LAN_NETWORK}" "${LAN_PARENT}" \
  "${LAN_SUBNET}" "${LAN_GATEWAY}" "${LAN_IP_RANGE}" "${LAN_AUX}"

printf '\nVerification:\n'
docker network inspect "${DMZ_NETWORK}" --format \
  '  {{.Name}}: driver={{.Driver}} scope={{.Scope}}'
docker network inspect "${LAN_NETWORK}" --format \
  '  {{.Name}}: driver={{.Driver}} scope={{.Scope}}'
