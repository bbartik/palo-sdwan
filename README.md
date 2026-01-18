# Palo Alto SDWAN Configuration Generator

Automates Palo Alto Networks IPSec tunnel configurations for SDWAN deployments without using the Panorama SDWAN plugin. Build your own AutoVPN-like hub-and-spoke topology using standard IPSec tunnels, SDWAN interfaces, and BGP.

## Features

- **Hub-and-spoke SDWAN topology** with automatic tunnel configuration
- **Dual output modes**: Panorama templates or standalone firewall configs
- **Multiple WAN links**: Support for MPLS, Internet, and other transport types
- **BGP peering** over loopback interfaces with automatic ASN assignment
- **GNS3 lab automation** for testing (optional)

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
.\venv\Scripts\activate      # Windows
source venv/bin/activate     # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Edit the topology model
#    Edit model-sdwan.yaml with your devices, interfaces, and tunnels

# 4. Generate configurations
python build-config.py
```

## Configuration Model

Edit `model-sdwan.yaml` to define your topology:

```yaml
# Output mode: "panorama" or "standalone"
target: panorama

members:
  hub1:
    sn: 007251000151812
    role: hub
    id: 1
    router_id: 192.168.180.1
    interfaces:
      wan1:
        name: ethernet1/1
        address: 192.168.2.1/24
        sdwan_gw: 192.168.2.2
      isp1:
        name: ethernet1/3
        address: 162.168.50.2/24
        sdwan_gw: 162.168.50.1
      lan1:
        name: ethernet1/4
        address: 192.168.80.1/24

  palo2:
    sn: 007251000151822
    role: branch
    id: 2
    router_id: 192.168.182.1
    interfaces:
      wan1:
        name: ethernet1/1
        address: 192.168.2.2/24
        sdwan_gw: 192.168.2.1
      # ... more interfaces

tunnels:
  - { branch: palo2, hub: hub1, bport: wan1, hport: wan1, subnet: 192.168.121.0/30 }
  - { branch: palo2, hub: hub1, bport: isp1, hport: isp1, subnet: 192.168.123.0/30 }

profiles:
  MPLS:
    tag: MPLS
    type: MPLS
    upload: 20
    download: 20
    tunnel: 'yes'
  Internet:
    tag: Internet
    type: Ethernet
    upload: 100
    download: 100
    tunnel: 'yes'
```

## Output Modes

### Panorama Mode (default)
```yaml
target: panorama
```
Generates `output/panorama-set.txt` with all device template configurations. Push to Panorama CLI or use the built-in push feature.

### Standalone Mode
```yaml
target: standalone
```
Generates individual files per device:
- `output/hub1.txt`
- `output/palo2.txt`
- `output/palo5.txt`

Paste these directly into each firewall's CLI.

## Interface Naming Convention

| Prefix | Zone | SDWAN Profile | Purpose |
|--------|------|---------------|---------|
| `wan*` | zone-to-branch/hub | MPLS | Private WAN links |
| `isp*` | zone-internet | Internet | Public internet links |
| `lan*` | zone-internal | - | LAN segments |

## What Gets Generated

- Template and template-stack configuration
- SDWAN interface profiles with path monitoring
- Physical interface configuration with SDWAN gateways
- Loopback interface for BGP router-id
- IKE gateways and IPSec tunnels
- SDWAN virtual interfaces grouping tunnels
- Static routes to remote sites
- BGP configuration with automatic ASN (65000 + device_id)
- Route redistribution for connected networks

## GNS3 Lab (Optional)

For testing, use the GNS3 lab script:

```bash
# Configure GNS3 settings in model-sdwan.yaml
gns3:
  server: 172.20.17.201
  port: 3080
  project_name: palo-sdwan-lab
  templates:
    paloalto: "PA-VM-11.1"
    c8000v: "c8000v"
    switch: "Ethernet switch"
    cloud: "Cloud"

# Create the lab
python gns3_lab.py create

# Start all nodes
python gns3_lab.py start

# Check status
python gns3_lab.py status

# Stop nodes
python gns3_lab.py stop

# Delete the project
python gns3_lab.py delete
```

## File Structure

```
palo-sdwan/
├── build-config.py      # Main configuration generator
├── gns3_lab.py          # GNS3 lab management (optional)
├── model-sdwan.yaml     # Topology definition
├── pa-set.j2            # Panorama template
├── pa-standalone.j2     # Standalone firewall template
├── requirements.txt     # Python dependencies
└── output/              # Generated configurations
    ├── panorama-set.txt # Panorama mode output
    ├── hub1.txt         # Standalone mode outputs
    ├── palo2.txt
    └── palo5.txt
```

## Requirements

- Python 3.8+
- Palo Alto PAN-OS 10.x+ (for SDWAN features)
- Panorama (for Panorama mode) or direct firewall access (for standalone mode)

## License

MIT
