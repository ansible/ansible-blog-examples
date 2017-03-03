#!/usr/bin/python
# -*- coding: utf8 -*-
#
# Ansible dynamic inventory script for reading from a Tower SCM project
# Requires: ansible, ansible-tower-cli
#
#    Copyright © 2016 Red Hat, Inc.
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

import inspect
import os
import sys

import json

from ansible.inventory import Inventory
from ansible.parsing.dataloader import DataLoader
from ansible.vars import VariableManager
from tower_cli import api


# Standard Tower project base path
BASE_PATH="/var/lib/awx/projects"

def rest_get(request):
    c = api.Client()
    response = c.get(request)
    if response.ok:
        j = response.json()
        if j.has_key('results'):
            return j['results'][0]
        else:
            return j
    else:
        return None

# Get ID from project name
def get_project_id(project):
    result = rest_get("projects/?name=%s" % (project,))
    if result:
        return result['id']
    else:
        return None

# If a project update is running, wait up two minutes for it to finish
def wait_for_project_update(project_id):
    retries = 120
    
    while retries > 0:
        result = rest_get("projects/%d" %(project_id,))
        if not result:
            return
        if not result['related'].has_key('current_update'):
            return
        sleep(1)
        retries = retries - 1
    return

# Find the toplevel path to the synced project's on-disk location
def get_file_path(project_id):
    result = rest_get("projects/%d" % (project_id,))
    if not result:
        return None
    return '%s/%s' % (BASE_PATH, result['local_path'])


# Read and parse inventory
def read_file(project_id, inv_file):
    file_path = get_file_path(project_id)
    if not file_path:
        return ""
    variable_manager = VariableManager()
    loader = DataLoader()
    inventory = Inventory(loader=loader, variable_manager=variable_manager,
                          host_list=os.path.join(file_path, inv_file))
    variable_manager.set_inventory(inventory)
    return inventory


def handle_missing_return_result(fn, member):
    # http://stackoverflow.com/a/197053
    vars = inspect.getargspec(fn)
    if 'return_results' in vars[0]:
        return fn(member, return_results=True)
    else:
        return fn(member)


def get_group_vars(group, inventory):
    return handle_missing_return_result(inventory.get_group_vars, group)


def get_host_vars(host, inventory):
    return handle_missing_return_result(inventory.get_host_vars, host)


# Convert inventory structure to JSON
def dump_json(inventory):
    ret = {}
    for group in inventory.groups.values():
        if group.name == 'all':
            continue
        g_obj = {}
        g_obj['children'] = []
        for child in group.child_groups:
            g_obj['children'].append(child.name)
        g_obj['hosts'] = []
        for host in group.hosts:
            g_obj['hosts'].append(host.name)
        g_obj['vars'] = get_group_vars(group, inventory)
        ret[group.name] = g_obj
    meta = dict(hostvars=dict())
    for host in inventory.list_hosts():
        if host.name not in meta['hostvars']:
            meta['hostvars'][host.name] = get_host_vars(host, inventory)
        else:
            meta['hostvars'][host.name].update(get_host_vars(host, inventory))
    ret['_meta'] = meta
    return json.dumps(ret)

try:
    project_name=os.environ.get("PROJECT_NAME")
except:
    project_name="Test project"
try:
    file_name=os.environ.get("INVENTORY_FILE")
except:
    file_name="inventory"


if len(sys.argv) > 1 and sys.argv[1] == '--list':
    project_id = get_project_id(project_name)
    if not project_id:
        sys.stderr.write("Could not find project '%s'\n" %(project_name,))
        sys.exit(1)

    wait_for_project_update(project_id)

    inv_contents = read_file(project_id, file_name)
    if not inv_contents:
        sys.stderr.write("Parse of inventory file '%s' in project '%s' failed\n" %(file_name, project_name))
        sys.exit(1)

    json_inv = dump_json(inv_contents)
    print json_inv
    sys.exit(0)
