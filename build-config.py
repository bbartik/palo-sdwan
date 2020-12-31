from jinja2 import FileSystemLoader, Environment
import yaml
import ipaddress
import glob
from netmiko import ConnectHandler
from getpass import getpass

import pdb


with open("model-sdwan.yaml", "r") as f:
    model = yaml.safe_load(f)


def build_device_models(model):

    # build list of remote ipsec endpoints
    # for hub this is all spokes, for spoke this is the hub

    members = model["members"]

    # hub = [ k for k, v in members.items() if members[k]["role"] == "hub" ]
    # branch = [ k for k, v in members.items() if members[k]["role"] == "branch" ]

    # build the model
    for m in members:

        for k in members[m]["interfaces"].copy().keys():
            if "wan" in k:
                members[m]["interfaces"][k].update({
                    "sdwan_profile": "MPLS",
                    "zone": "zone-to-branch"
                })
            elif "isp" in k:
                members[m]["interfaces"][k].update({
                    "sdwan_profile": "Internet",
                    "zone": "zone-internet"
                })
            elif "lan" in k:
                continue
            else:
                print(f"Unsupported interface name {k} found. Exiting.")

        # determine who the remotes are based on whether we are processing hub or branch
        if "hub" in members[m]["role"]:
            hb = "hub"
            peer = "branch"
            remote_sites = [k for k, v in members.items() if members[k]["role"] == "branch"]
            index = 1
        if "branch" in members[m]["role"]:
            hb = "branch"
            peer = "hub"
            remote_sites = [k for k, v in members.items() if members[k]["role"] == "hub"]
            index = 2

        # initialize the remote device object
        remotes = {}
        for r in remote_sites:
            sdwan_intf = int(members[r]["id"]) + 100
            loopback = members[r]["router_id"]
            remote_wans = {}
            # build object for static route to remote edge subnets (e.g. tunnel endpoint)
            for k, v in members[r]["interfaces"].items():
                try:
                    # we only do this for l3 wans, not l2 which are directly connected anyway
                    isL3 = v["l3"]
                    subnet = str(ipaddress.ip_interface(v["address"]).network)
                    # assumes each device follows standard (e1/1 connects to e1/1)
                    intf = members[m]["interfaces"][k]["name"]
                    gw = members[m]["interfaces"][k]["sdwan_gw"]
                    remote_wans.update({
                        subnet: {
                            "intf": intf,
                            "gw": gw,
                        }
                    })
                except:
                    next

            tunnels = {}
            for t in model["tunnels"]:
                if m in t[hb] and r in t[peer]:

                    # build tunnels, one per interface in this version
                    # change this if you want different naming
                    name = f"{r}_{k}"
                    # tunnel number = XX + YY where XX is site id, YY is eth
                    # example: 0501 would be site 5, ethernet 1/1
                    # obviously this need to change of site ifs are > 100
                    #pdb.set_trace()
                    site_id = members[r]["id"]
                    bport = members[r]["interfaces"].get(t["bport"])["name"]
                    eth_id = int(bport.split("/")[1])
                    tunnel_number = int(f"{site_id:02d}{eth_id:02d}")
                    #pdb.set_trace()
                    tunnel_intf = f"tunnel.{tunnel_number}"
                    ip = str(ipaddress.ip_interface(t["subnet"]) + index).replace("32", "30")
                    monitor_ip = str(ipaddress.ip_interface(t["subnet"]) + (3-index)).replace("/32", "")
                    # get local port by using name "wan1", etc
                    local_intf = members[m]["interfaces"].get(t["hport"])["name"]
                    local_ip = members[m]["interfaces"].get(t["hport"])["address"]
                    peer_ip = members[r]["interfaces"].get(t["bport"])["address"].split("/")[0]
                    name = f"{r}_{t['hport']}"
                    #print(t, name, tunnel_intf, ip, monitor_ip, local_intf, local_ip, peer_ip)
                    tunnels.update({
                        name: {
                            "intf": tunnel_intf,
                            "ip": ip,
                            "monitor_ip": monitor_ip,
                            "local_intf": local_intf,
                            "local_ip": local_ip,
                            "peer_ip": peer_ip,
                        }
                    })

            remotes.update({
                r: {
                    "sdwan_intf": sdwan_intf,
                    "loopback": loopback,
                    "remote_wans": remote_wans,
                    "tunnels": tunnels,
                }
            })    

        device_model = {}
        device_model.update({
            "name": m,
            "sn": members[m]["sn"],
            "id": members[m]["id"],
            "role": members[m]["role"],
            "template": m,
            "router_id": members[m]["router_id"],
            "interfaces": members[m]["interfaces"],
            "remotes": remotes,
            "profiles": model["profiles"],
        })


        file_loader = FileSystemLoader("./")
        env = Environment(loader=file_loader)
        template = env.get_template('model-device.j2')
        output = template.render(vars=device_model)

        with open(f"output/model-{m}.yaml", "w") as f:
            f.write(output)


def build_config(devices):

    for d in devices:
        with open(f"output/model-{d}.yaml", "r") as f:
            data = yaml.safe_load(f)

        file_loader = FileSystemLoader("./")
        env = Environment(loader=file_loader)
        template = env.get_template('pa-set.j2')
        output = template.render(vars=data)

        with open(f"output/pa-{d}-template-set.txt", "w") as f:
            f.write(output)

    return None


def push_config():

    host = input("Enter your hostname: ")
    password = getpass("Enter password: ")

    device = { 
        "device_type": "paloalto_panos",
        "host": host,
        "username": "admin",
        "password": "password",
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

    #pdb.set_trace()

if __name__ == "__main__":

    build_device_models(model)
    devices = [ k for k, v in model["members"].items()]
    build_config(devices)

    answer = input("Push config to Panorama? [y/n] ")
    if answer == "y":
        push_config()