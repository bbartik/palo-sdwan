#!/usr/bin/env python3
"""
GNS3 Lab Management Script for Palo Alto SDWAN Lab

This script creates, manages, and tears down a GNS3 lab topology for testing
Palo Alto SDWAN configurations.

Topology:
                           [Cloud]
                              |
                       [Mgmt/Ext Switch]
                      /    |    |    |    \\
                 [Hub1] [Palo2] [Palo5] [ISP1] [ISP2]
                    \\      |      /       |       |
                     \\     |     /        |       |
                      +----+----+---------+       |
                      |  ISP1 direct links        |
                      |  Gi2->e1/1, Gi3->e1/1...  |
                      |                           |
                      +---------------------------+
                         ISP2 direct links + ISP1<->ISP2 link

ISP1 Router (c8000v):
  - GigabitEthernet1: mgmt/ext switch (external/mgmt)
  - GigabitEthernet2: hub1 ethernet1/1 (wan1)
  - GigabitEthernet3: palo2 ethernet1/1 (wan1)
  - GigabitEthernet4: palo5 ethernet1/1 (wan1)
  - GigabitEthernet5: ISP2 GigabitEthernet5 (inter-ISP link)

ISP2 Router (c8000v):
  - GigabitEthernet1: mgmt/ext switch (external/mgmt)
  - GigabitEthernet2: hub1 ethernet1/2 (wan2)
  - GigabitEthernet3: palo2 ethernet1/2 (wan2)
  - GigabitEthernet4: palo5 ethernet1/2 (wan2)
  - GigabitEthernet5: ISP1 GigabitEthernet5 (inter-ISP link)

Usage:
    python gns3_lab.py create   - Create the lab project and nodes
    python gns3_lab.py start    - Start all nodes
    python gns3_lab.py stop     - Stop all nodes
    python gns3_lab.py delete   - Delete the entire project
    python gns3_lab.py status   - Show project status
"""

import sys
import yaml
import time
import requests


def load_config():
    """Load configuration from model-sdwan.yaml"""
    with open("model-sdwan.yaml", "r") as f:
        model = yaml.safe_load(f)
    return model


class GNS3Client:
    """Simple GNS3 API client that avoids gns3fy pydantic issues"""

    def __init__(self, server, port=3080):
        self.base_url = f"http://{server}:{port}/v2"
        self.session = requests.Session()
        print(f"Connecting to GNS3 server at http://{server}:{port}")

    def _request(self, method, endpoint, json=None):
        url = f"{self.base_url}{endpoint}"
        resp = self.session.request(method, url, json=json)
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def get_projects(self):
        return self._request("GET", "/projects")

    def create_project(self, name):
        return self._request("POST", "/projects", json={"name": name})

    def get_project(self, project_id):
        return self._request("GET", f"/projects/{project_id}")

    def open_project(self, project_id):
        return self._request("POST", f"/projects/{project_id}/open")

    def delete_project(self, project_id):
        return self._request("DELETE", f"/projects/{project_id}")

    def get_templates(self):
        return self._request("GET", "/templates")

    def create_node_builtin(self, project_id, name, node_type, x=0, y=0, properties=None):
        """Create a builtin node (cloud, ethernet_switch, etc.)"""
        payload = {
            "name": name,
            "node_type": node_type,
            "compute_id": "local",
            "x": x,
            "y": y,
            "symbol": f":/symbols/{node_type}.svg"
        }
        if properties:
            payload["properties"] = properties
        return self._request("POST", f"/projects/{project_id}/nodes", json=payload)

    def create_node_from_template(self, project_id, template_id, name, x=0, y=0):
        """Create a node from a template (QEMU VMs, etc.)"""
        return self._request("POST", f"/projects/{project_id}/templates/{template_id}", json={
            "name": name,
            "x": x,
            "y": y
        })

    def get_nodes(self, project_id):
        return self._request("GET", f"/projects/{project_id}/nodes")

    def start_node(self, project_id, node_id):
        return self._request("POST", f"/projects/{project_id}/nodes/{node_id}/start")

    def stop_node(self, project_id, node_id):
        return self._request("POST", f"/projects/{project_id}/nodes/{node_id}/stop")

    def create_link(self, project_id, nodes, label1=None, label2=None):
        """Create a link between two nodes with optional port labels"""
        payload = {"nodes": nodes}
        # Add labels to show interface names on the diagram
        if label1 or label2:
            payload["nodes"][0]["label"] = {"text": label1 or ""}
            payload["nodes"][1]["label"] = {"text": label2 or ""}
        return self._request("POST", f"/projects/{project_id}/links", json=payload)

    def get_links(self, project_id):
        return self._request("GET", f"/projects/{project_id}/links")


def get_gns3_client(config):
    """Create GNS3 API client"""
    gns3_config = config.get("gns3", {})
    server = gns3_config.get("server", "172.20.17.201")
    port = gns3_config.get("port", 3080)
    return GNS3Client(server, port)


def get_or_create_project(client, config):
    """Get existing project or create new one"""
    gns3_config = config.get("gns3", {})
    project_name = gns3_config.get("project_name", "palo-sdwan-lab")

    # Check if project exists
    projects = client.get_projects()
    for proj in projects:
        if proj["name"] == project_name:
            print(f"Found existing project: {project_name}")
            if proj["status"] != "opened":
                client.open_project(proj["project_id"])
            return proj

    # Create new project
    print(f"Creating new project: {project_name}")
    project = client.create_project(project_name)
    client.open_project(project["project_id"])
    return project


def get_template_id(client, template_name):
    """Get template ID by name"""
    templates = client.get_templates()
    for template in templates:
        if template["name"] == template_name:
            return template["template_id"]
    raise ValueError(f"Template '{template_name}' not found on GNS3 server")


def create_lab(config):
    """Create the full lab topology"""
    client = get_gns3_client(config)
    project = get_or_create_project(client, config)
    project_id = project["project_id"]

    gns3_config = config.get("gns3", {})
    templates = gns3_config.get("templates", {})
    mgmt_interface = gns3_config.get("mgmt_cloud_interface", "eth0")

    # Get template IDs for QEMU VM types (Palo Alto, c8000v)
    try:
        pa_template_id = get_template_id(client, templates.get("paloalto", "PA-VM-11.1"))
        c8000v_template_id = get_template_id(client, templates.get("c8000v", "c8000v"))
    except ValueError as e:
        print(f"Error: {e}")
        print("Available templates:")
        for t in client.get_templates():
            print(f"  - {t['name']} (type: {t.get('template_type', 'unknown')})")
        return

    nodes = {}

    # Define node positions for nice layout
    positions = {
        "cloud": (0, -300),
        "mgmt_switch": (0, -100),
        "hub1": (-300, 100),
        "palo2": (0, 100),
        "palo5": (300, 100),
        "isp1": (-150, 350),
        "isp2": (150, 350),
    }

    # Create Cloud node (builtin type with proper symbol)
    print("Creating Cloud node...")
    nodes["cloud"] = client.create_node_builtin(
        project_id, "cloud", "cloud",
        x=positions["cloud"][0], y=positions["cloud"][1],
        properties={"ports_mapping": [{"name": mgmt_interface, "port_number": 0, "type": "ethernet", "interface": mgmt_interface}]}
    )

    # Create Management/External Switch (builtin type with proper symbol)
    print("Creating mgmt_switch...")
    nodes["mgmt_switch"] = client.create_node_builtin(
        project_id, "mgmt_switch", "ethernet_switch",
        x=positions["mgmt_switch"][0], y=positions["mgmt_switch"][1],
        properties={"ports_mapping": [
            {"name": f"Ethernet{i}", "port_number": i, "type": "access", "vlan": 1}
            for i in range(8)
        ]}
    )

    # Create Palo Alto firewalls (from template)
    for fw_name in ["hub1", "palo2", "palo5"]:
        print(f"Creating {fw_name}...")
        nodes[fw_name] = client.create_node_from_template(project_id, pa_template_id, fw_name,
                                                           x=positions[fw_name][0], y=positions[fw_name][1])

    # Create C8000V ISP routers (from template)
    for router_name in ["isp1", "isp2"]:
        print(f"Creating {router_name}...")
        nodes[router_name] = client.create_node_from_template(project_id, c8000v_template_id, router_name,
                                                               x=positions[router_name][0], y=positions[router_name][1])

    # Wait for nodes to be ready
    time.sleep(2)

    print("\nCreating links...")

    # Refresh nodes to get port info
    refreshed_nodes = {n["name"]: n for n in client.get_nodes(project_id)}
    nodes = refreshed_nodes

    # Debug: print port info for each node
    print("\n-- Node port information --")
    for name, node in nodes.items():
        print(f"{name}:")
        for port in node.get("ports", []):
            print(f"  adapter {port.get('adapter_number')}, port {port.get('port_number')}: {port.get('name', port.get('short_name', 'unnamed'))}")

    # Helper to find port by adapter number
    def find_port(node, adapter_number, port_number=0):
        for port in node.get("ports", []):
            if port.get("adapter_number") == adapter_number and port.get("port_number") == port_number:
                return port
        return None

    # Helper to find switch port by port number
    def find_switch_port(node, port_number):
        for port in node.get("ports", []):
            if port.get("port_number") == port_number:
                return port
        return None

    def create_link(node1_name, adapter1, port1, node2_name, adapter2, port2, label1=None, label2=None):
        """Helper to create a link between two nodes with interface labels"""
        try:
            print(f"  Linking: {node1_name} ({label1}) <-> {node2_name} ({label2})")
            client.create_link(project_id, [
                {"node_id": nodes[node1_name]["node_id"],
                 "adapter_number": adapter1,
                 "port_number": port1},
                {"node_id": nodes[node2_name]["node_id"],
                 "adapter_number": adapter2,
                 "port_number": port2},
            ], label1=label1, label2=label2)
        except Exception as e:
            print(f"    Warning: Could not create link: {e}")

    # === MGMT/EXT SWITCH CONNECTIONS ===
    # Switch port 0: Cloud
    # Switch port 1: hub1 mgmt (adapter 0)
    # Switch port 2: palo2 mgmt (adapter 0)
    # Switch port 3: palo5 mgmt (adapter 0)
    # Switch port 4: isp1 Gi1 (adapter 0)
    # Switch port 5: isp2 Gi1 (adapter 0)

    print("\n-- Mgmt/Ext Switch connections --")

    # Cloud to mgmt switch (cloud adapter 0, switch port 0)
    create_link("cloud", 0, 0, "mgmt_switch", 0, 0, mgmt_interface, "Ethernet0")

    # Palo mgmt ports to switch (Palo adapter 0 = mgmt)
    create_link("hub1", 0, 0, "mgmt_switch", 0, 1, "mgmt", "Ethernet1")
    create_link("palo2", 0, 0, "mgmt_switch", 0, 2, "mgmt", "Ethernet2")
    create_link("palo5", 0, 0, "mgmt_switch", 0, 3, "mgmt", "Ethernet3")

    # ISP router Gi1 (adapter 0) to switch
    create_link("isp1", 0, 0, "mgmt_switch", 0, 4, "Gi1", "Ethernet4")
    create_link("isp2", 0, 0, "mgmt_switch", 0, 5, "Gi1", "Ethernet5")

    # === ISP1 ROUTER DIRECT CONNECTIONS ===
    # Gi2 (adapter 1) -> hub1 e1/1 (adapter 1)
    # Gi3 (adapter 2) -> palo2 e1/1 (adapter 1)
    # Gi4 (adapter 3) -> palo5 e1/1 (adapter 1)

    print("\n-- ISP1 Router direct connections --")

    create_link("isp1", 1, 0, "hub1", 1, 0, "Gi2", "e1/1")
    create_link("isp1", 2, 0, "palo2", 1, 0, "Gi3", "e1/1")
    create_link("isp1", 3, 0, "palo5", 1, 0, "Gi4", "e1/1")

    # === ISP2 ROUTER DIRECT CONNECTIONS ===
    # Gi2 (adapter 1) -> hub1 e1/2 (adapter 2)
    # Gi3 (adapter 2) -> palo2 e1/2 (adapter 2)
    # Gi4 (adapter 3) -> palo5 e1/2 (adapter 2)

    print("\n-- ISP2 Router direct connections --")

    create_link("isp2", 1, 0, "hub1", 2, 0, "Gi2", "e1/2")
    create_link("isp2", 2, 0, "palo2", 2, 0, "Gi3", "e1/2")
    create_link("isp2", 3, 0, "palo5", 2, 0, "Gi4", "e1/2")

    # Inter-ISP link: ISP1 Gi5 <-> ISP2 Gi5
    print("\n-- Inter-ISP link --")
    create_link("isp1", 4, 0, "isp2", 4, 0, "Gi5", "Gi5")

    print(f"\nLab created successfully!")
    print(f"Project: {project['name']}")
    print(f"Nodes: {len(nodes)}")
    print("\nTopology Summary:")
    print("  - cloud -> mgmt_switch")
    print("  - mgmt_switch -> hub1/palo2/palo5 (mgmt ports)")
    print("  - mgmt_switch -> isp1/isp2 (Gi1 external interfaces)")
    print("  - isp1: Gi2->hub1 e1/1, Gi3->palo2 e1/1, Gi4->palo5 e1/1")
    print("  - isp2: Gi2->hub1 e1/2, Gi3->palo2 e1/2, Gi4->palo5 e1/2")
    print("  - isp1 Gi5 <-> isp2 Gi5 (inter-ISP link)")


def start_lab(config):
    """Start all nodes in the lab"""
    client = get_gns3_client(config)
    project = get_or_create_project(client, config)
    project_id = project["project_id"]

    print("Starting all nodes...")
    nodes = client.get_nodes(project_id)
    for node in nodes:
        print(f"  Starting {node['name']}...")
        try:
            client.start_node(project_id, node["node_id"])
        except Exception as e:
            print(f"    Warning: {e}")
    print("All nodes started!")


def stop_lab(config):
    """Stop all nodes in the lab"""
    client = get_gns3_client(config)
    project = get_or_create_project(client, config)
    project_id = project["project_id"]

    print("Stopping all nodes...")
    nodes = client.get_nodes(project_id)
    for node in nodes:
        print(f"  Stopping {node['name']}...")
        try:
            client.stop_node(project_id, node["node_id"])
        except Exception as e:
            print(f"    Warning: {e}")
    print("All nodes stopped!")


def delete_lab(config):
    """Delete the entire lab project"""
    client = get_gns3_client(config)
    gns3_config = config.get("gns3", {})
    project_name = gns3_config.get("project_name", "palo-sdwan-lab")

    projects = client.get_projects()
    for proj in projects:
        if proj["name"] == project_name:
            confirm = input(f"Are you sure you want to delete project '{project_name}'? [y/N] ")
            if confirm.lower() == "y":
                client.delete_project(proj["project_id"])
                print(f"Project '{project_name}' deleted!")
            else:
                print("Cancelled.")
            return

    print(f"Project '{project_name}' not found.")


def show_status(config):
    """Show lab status"""
    client = get_gns3_client(config)
    gns3_config = config.get("gns3", {})
    project_name = gns3_config.get("project_name", "palo-sdwan-lab")

    projects = client.get_projects()
    for proj in projects:
        if proj["name"] == project_name:
            print(f"Project: {proj['name']}")
            print(f"Status: {proj['status']}")
            print(f"\nNodes:")

            if proj["status"] == "opened":
                nodes = client.get_nodes(proj["project_id"])
                for node in nodes:
                    print(f"  - {node['name']}: {node.get('status', 'unknown')}")
            else:
                print("  (Project not opened)")
            return

    print(f"Project '{project_name}' not found.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    config = load_config()

    commands = {
        "create": create_lab,
        "start": start_lab,
        "stop": stop_lab,
        "delete": delete_lab,
        "status": show_status,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print("Available commands: create, start, stop, delete, status")
        sys.exit(1)

    commands[command](config)


if __name__ == "__main__":
    main()
