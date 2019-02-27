#!/bin/bash
set -ex
pykwalify -s schema.yaml -d resources.yaml
ansible-vault decrypt userdata.yaml
python ensure_enough.py || true
ansible-vault encrypt userdata.yaml
