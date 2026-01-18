#!/usr/bin/env python3
"""
Palo Alto SDWAN Configuration Generator

Generates IPSec tunnel configurations for Palo Alto SDWAN deployments.
Supports both Panorama and standalone firewall output modes.

Tunnel mesh is auto-generated between hubs and spokes using all available
WAN interfaces (isp1, isp2, wan1, wan2, etc.)
"""

from jinja2 import FileSystemLoader, Environment
import yaml
import ipaddress
import glob
from netmiko import ConnectHandler
from getpass import getpass


with open("model-sdwan.yaml", "r") as f:
    model = yaml.safe_load(f)

# Get output target from model (default to panorama)
OUTPUT_TARGET = model.get("target", "panorama")


def get_wan_interfaces(member_data):
    """
    Get all WAN interfaces (isp* or wan*) for a member.
    Returns dict of interface key -> interface data
    """
    wan_intfs = {}
    for intf_key, intf_data in member_data.get("interfaces", {}).items():
        if intf_key.startswith("isp") or intf_key.startswith("wan"):
            wan_intfs[intf_key] = intf_data
    return wan_intfs


def get_tunnel_pool(model):
    """Get tunnel IP pool from model, default to 100.64.0.0/16"""
    tunnels_config = model.get("tunnels", {})
    if isinstance(tunnels_config, dict):
        pool_str = tunnels_config.get("pool", "100.64.0.0/16")
    else:
        pool_str = "100.64.0.0/16"
    return ipaddress.ip_network(pool_str)


def generate_tunnel_mesh(model):
    """
    Generate full mesh of tunnels between hubs and spokes.

    For each hub-spoke pair, creates tunnels for all combinations of WAN interfaces.
    Example: hub1(isp1,isp2) <-> palo2(isp1,isp2) = 4 tunnels

    Tunnel IPs are allocated from pool using remote device ID in 3rd octet:
    - 100.64.<remote_id>.<offset>/31

    Returns dict of tunnels keyed by (hub_name, spoke_name, hub_intf, spoke_intf)
    """
    members = model["members"]
    pool = get_tunnel_pool(model)
    pool_base = pool.network_address

    hubs = {k: v for k, v in members.items() if v["role"] == "hub"}
    spokes = {k: v for k, v in members.items() if v["role"] == "branch"}

    tunnels = {}

    for hub_name, hub_data in hubs.items():
        hub_wans = get_wan_interfaces(hub_data)

        for spoke_name, spoke_data in spokes.items():
            spoke_wans = get_wan_interfaces(spoke_data)
            spoke_id = spoke_data["id"]

            # Generate all combinations of hub WAN x spoke WAN
            tunnel_offset = 0
            for hub_intf_key in sorted(hub_wans.keys()):
                for spoke_intf_key in sorted(spoke_wans.keys()):
                    # Calculate tunnel IPs using spoke ID in 3rd octet
                    # 100.64.<spoke_id>.<offset> for hub side
                    # 100.64.<spoke_id>.<offset+1> for spoke side
                    base_ip = ipaddress.ip_address(
                        int(pool_base) + (spoke_id << 8) + tunnel_offset
                    )
                    hub_tunnel_ip = f"{base_ip}/31"
                    spoke_tunnel_ip = f"{base_ip + 1}/31"

                    tunnel_key = (hub_name, spoke_name, hub_intf_key, spoke_intf_key)
                    tunnels[tunnel_key] = {
                        "hub_name": hub_name,
                        "spoke_name": spoke_name,
                        "hub_intf_key": hub_intf_key,
                        "spoke_intf_key": spoke_intf_key,
                        "hub_intf": hub_wans[hub_intf_key],
                        "spoke_intf": spoke_wans[spoke_intf_key],
                        "hub_tunnel_ip": hub_tunnel_ip,
                        "spoke_tunnel_ip": spoke_tunnel_ip,
                        "hub_monitor_ip": str(base_ip + 1),
                        "spoke_monitor_ip": str(base_ip),
                    }

                    tunnel_offset += 2  # Move to next /31

    return tunnels


def build_device_models(model):
    """
    Build device-specific models from the topology definition.

    Returns:
        dict: Dictionary of device models keyed by device name
    """
    members = model["members"]
    device_models = {}

    # Generate the full tunnel mesh
    tunnel_mesh = generate_tunnel_mesh(model)

    for m in members:
        member_data = members[m]
        role = member_data["role"]

        # Set the zone and sdwan profiles for each interface
        for k in member_data["interfaces"].copy().keys():
            intf = member_data["interfaces"][k]

            if k.startswith("wan"):
                # MPLS/private WAN
                if role == "hub":
                    intf.update({"sdwan_profile": "MPLS", "zone": "zone-to-branch"})
                else:
                    intf.update({"sdwan_profile": "MPLS", "zone": "zone-to-hub"})
            elif k.startswith("isp"):
                # Internet/ISP - use the profile name that matches the interface
                # e.g., isp1 -> ISP1 profile, isp2 -> ISP2 profile
                profile_name = k.upper()  # isp1 -> ISP1
                if profile_name not in model.get("profiles", {}):
                    profile_name = "Internet"  # fallback
                # ISP interfaces go in zone-internet (not the tunnel zone)
                intf.update({"sdwan_profile": profile_name, "zone": "zone-internet"})
            elif k.startswith("lan"):
                if "zone" not in intf:
                    intf["zone"] = "zone-internal"
            else:
                print(f"Warning: Unknown interface type '{k}' - skipping zone/profile assignment")

        # Determine remote sites based on role
        if role == "hub":
            remote_sites = [k for k, v in members.items() if v["role"] == "branch"]
        else:
            remote_sites = [k for k, v in members.items() if v["role"] == "hub"]

        # Build remote device objects with tunnels
        remotes = {}
        for r in remote_sites:
            remote_data = members[r]
            sdwan_intf = int(remote_data["id"]) + 100
            loopback = remote_data["router_id"]

            # Build static routes for L3 remote WANs
            remote_wans = {}
            for k, v in remote_data["interfaces"].items():
                try:
                    if v.get("l3") and k in member_data["interfaces"]:
                        subnet = str(ipaddress.ip_interface(v["address"]).network)
                        local_intf = member_data["interfaces"][k]["name"]
                        gw = member_data["interfaces"][k]["sdwan_gw"]
                        remote_wans[subnet] = {"intf": local_intf, "gw": gw}
                except (KeyError, TypeError):
                    pass

            # Build tunnels for this remote
            tunnels = {}
            tunnel_count = 0

            for tunnel_key, tunnel_data in tunnel_mesh.items():
                hub_name, spoke_name, hub_intf_key, spoke_intf_key = tunnel_key

                # Check if this tunnel involves current device (m) and remote (r)
                if role == "hub" and m == hub_name and r == spoke_name:
                    # This device is the hub
                    tunnel_name = f"{spoke_name}_{hub_intf_key}_{spoke_intf_key}"
                    tunnel_number = int(f"{remote_data['id']}{tunnel_count:02d}")

                    tunnels[tunnel_name] = {
                        "intf": f"tunnel.{tunnel_number}",
                        "ip": tunnel_data["hub_tunnel_ip"],
                        "monitor_ip": tunnel_data["hub_monitor_ip"],
                        "local_intf": tunnel_data["hub_intf"]["name"],
                        "local_ip": tunnel_data["hub_intf"]["address"],  # Keep mask for IKE gateway
                        "peer_ip": tunnel_data["spoke_intf"]["address"].split("/")[0],
                    }
                    tunnel_count += 1

                elif role == "branch" and m == spoke_name and r == hub_name:
                    # This device is the spoke
                    tunnel_name = f"{hub_name}_{spoke_intf_key}_{hub_intf_key}"
                    tunnel_number = int(f"{remote_data['id']}{tunnel_count:02d}")

                    tunnels[tunnel_name] = {
                        "intf": f"tunnel.{tunnel_number}",
                        "ip": tunnel_data["spoke_tunnel_ip"],
                        "monitor_ip": tunnel_data["spoke_monitor_ip"],
                        "local_intf": tunnel_data["spoke_intf"]["name"],
                        "local_ip": tunnel_data["spoke_intf"]["address"],  # Keep mask for IKE gateway
                        "peer_ip": tunnel_data["hub_intf"]["address"].split("/")[0],
                    }
                    tunnel_count += 1

            remotes[r] = {
                "id": remote_data["id"],
                "sdwan_intf": sdwan_intf,
                "loopback": loopback,
                "remote_wans": remote_wans,
                "tunnels": tunnels,
            }

        # Build the complete device model
        device_model = {
            "name": m,
            "sn": member_data["sn"],
            "id": member_data["id"],
            "role": role,
            "template": m,
            "loopback": member_data["router_id"],
            "asn": 65000 + member_data["id"],
            "interfaces": member_data["interfaces"],
            "remotes": remotes,
            "profiles": model.get("profiles", {}),
        }

        device_models[m] = device_model

    return device_models


def build_config(device_models, target="panorama"):
    """
    Build configuration files based on target mode.

    Args:
        device_models: Dictionary of device models from build_device_models()
        target: "panorama" for single panorama-set.txt, "standalone" for individual files
    """
    file_loader = FileSystemLoader("./")
    env = Environment(loader=file_loader)

    if target == "panorama":
        template = env.get_template('pa-set.j2')
        all_outputs = []

        for name, data in device_models.items():
            output = template.render(vars=data)
            all_outputs.append(f"# ===== Configuration for {name} =====\n{output}")

        with open("output/panorama-set.txt", "w") as f:
            f.write("\n\n".join(all_outputs))
        print(f"Generated: output/panorama-set.txt")

    else:
        template = env.get_template('pa-standalone.j2')

        for name, data in device_models.items():
            output = template.render(vars=data)
            with open(f"output/{name}.txt", "w") as f:
                f.write(output)
            print(f"Generated: output/{name}.txt")


def print_tunnel_summary(model):
    """Print a summary of generated tunnels for verification."""
    tunnel_mesh = generate_tunnel_mesh(model)

    print("\n=== Tunnel Mesh Summary ===")

    # Group by spoke for cleaner output
    by_spoke = {}
    for key, data in tunnel_mesh.items():
        hub_name, spoke_name, hub_intf, spoke_intf = key
        if spoke_name not in by_spoke:
            by_spoke[spoke_name] = []
        by_spoke[spoke_name].append((hub_name, hub_intf, spoke_intf, data))

    for spoke_name in sorted(by_spoke.keys()):
        spoke_id = model["members"][spoke_name]["id"]
        print(f"\n{spoke_name} (id={spoke_id}, ASN=65{spoke_id:03d}):")
        for hub_name, hub_intf, spoke_intf, data in by_spoke[spoke_name]:
            print(f"  {hub_name} {hub_intf} <-> {spoke_name} {spoke_intf}: "
                  f"{data['hub_tunnel_ip'].split('/')[0]} <-> {data['spoke_tunnel_ip'].split('/')[0]}")


def push_config():
    """Push configuration to Panorama via SSH."""
    host = input("Enter your hostname: ")
    password = getpass("Enter password: ")

    device = {
        "device_type": "paloalto_panos",
        "host": host,
        "username": "admin",
        "password": password,
        "verbose": True,
        "session_log": "output.txt",
    }

    net_connect = ConnectHandler(**device)
    output = net_connect.send_command("show admins")
    print(output)

    set_files = glob.glob('./output/*.txt')

    for sf in set_files:
        with open(sf, "r") as f:
            cmds = f.readlines()
        output = net_connect.send_config_set(cmds)


if __name__ == "__main__":
    # Print tunnel summary
    print_tunnel_summary(model)

    # Build device models
    device_models = build_device_models(model)

    # Generate configurations
    print(f"\nBuilding configs with target: {OUTPUT_TARGET}")
    build_config(device_models, target=OUTPUT_TARGET)

    # Optionally push to Panorama
    if OUTPUT_TARGET == "panorama":
        answer = input("Push config to Panorama? [y/n] ")
        if answer == "y":
            push_config()
    else:
        print("Standalone configs generated. Push manually to each firewall.")
