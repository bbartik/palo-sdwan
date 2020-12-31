# palo-sdwan
This project is built to automate Palo Alto Panorama configuration templates for the IPSec tunnels needed for Palo Alto SDWAN.

## output

The current output is "set" commands intended to be applied on Panorama CLI. The script will prompt you to load these into Panorama as well. There is one .txt file per template. In addition, the device specific model is written to this directory for reference.

## how it works

- Edit the model-sdwan.yaml file
- Run "python build-config.py"

## future

Future support for pan-os-python sdk will be added.



