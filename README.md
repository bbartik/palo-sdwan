# palo-sdwan
This project is built to automate Palo Alto Panorama configuration templates for the IPSec tunnels needed for Palo Alto SDWAN. Panorama supports and Auto VPN feature but this does not always work as intended and also has a very rigid naming scheme which is not user friendly.

## output

The current output is "set" commands intended to be applied on Panorama CLI. There is one .txt file per template. In addition, the device specific model is written to this directory for reference.

## how it works

- Edit the model-sdwan.yaml file
- Run "python build-config.py"
- Check the outputs folder and copy the .txt file templates into Panorama
- Adjust or add parameters as needed (The configs are meant to automate only the tunnels, basic L3 interfaces, BGP and some static routing).

## future

Future support for pan-os-python sdk will be added.



