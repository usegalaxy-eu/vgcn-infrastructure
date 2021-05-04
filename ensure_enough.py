#!/usr/bin/env python
import argparse
import copy
import datetime
import json
import logging
import os
import paramiko
import random
import re
import subprocess
import tempfile
import time
import yaml


logging.basicConfig(level=logging.INFO)


class VgcnPolicy(paramiko.client.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key, vgcn_pubkeys):
        """Custom policy that only accepts known VGCN public key(s)"""
        if key.get_base64() not in vgcn_pubkeys:
            raise Exception("Untrusted Host")


class StateManagement:

    def __init__(self, args=None):
        self.resources_file = args.resources_file
        self.userdata_file = args.userdata_file
        self.dry_run = args.dry_run

        logging.info('resources file: {}'.format(self.resources_file))
        logging.info('userdata file: {}'.format(self.userdata_file))
        logging.info('Dry run mode: {}'.format(self.dry_run))

        with open(self.resources_file, 'r') as handle:
            self.config = yaml.safe_load(handle)

        with open(self.userdata_file, 'r') as handle:
            self.user_data = handle.read()

        self.current_image_name = self.config['image']
        self.vgcn_pubkeys = self.config['pubkeys']
        self.today = datetime.date.today()

    @staticmethod
    def os_command(args, is_json=True, cmd=None):
        lcmd = ['openstack' if not cmd else cmd] + list(args)
        if is_json:
            lcmd += ['-f', 'json']
        logging.debug(' '.join(lcmd))
        q = subprocess.check_output(lcmd)
        # logging.debug(q)
        if is_json:
            return json.loads(q)
        else:
            return q

    @staticmethod
    def remote_command(hostname, command, username='centos', port=22):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(VgcnPolicy)
        logging.debug("Connecting to %s@%s:%s", username, hostname, port)
        client.connect(hostname, port=port, username=username)

        logging.debug("executing: %s", command)
        stdin, stdout, stderr = client.exec_command(command)
        # Returned as 'bytes' in py3k
        stdout_decoded = stdout.read().decode('utf-8')
        stderr_decoded = stderr.read().decode('utf-8')
        return stdout_decoded, stderr_decoded

    @staticmethod
    def non_conflicting_name(prefix, existing_servers):
        """
        Generate a name for the machine that's unique to the machine and not used
        by any existing ones.

        :param str prefix: the name prefix, usually vgcnbwc-{resource_identifier}
        :param list(Nova) existing_servers: list of existing servers against which
                                            we will check the names.
        """
        server_names = [x['Name'] for x in existing_servers]
        # Make at least ten tries
        for i in range(10):
            # generate a test name, similar style to jenkins images.
            test_name = '%s-%04d' % (prefix, random.randint(0, 9999))
            # If unused, we can use this.
            if test_name not in server_names:
                return test_name

        # Generate a failsafe name to ensure deterministic exiting.
        return '%s-%f' % (prefix, time.time())

    def identify_server_group(self, server_identifier):
        """
        Identify a list of servers starting with some specific prefix, and mark
        those of the current image as OK while those with a different image are
        marked TO REMOVE

        :param str server_identifier: A string that prefixes all servers of that group, e.g. `vgcnbwc-training...`

        :returns: a set of servers to REMOVE and a set of TO KEEP
        :rtype: tuple(list, list)
        """
        servers_rm = []
        servers_ok = []
        # All servers
        for server in sorted(self.os_command(['server', 'list']), key=lambda x: x['Name']):
            # Filter by those with our server_identifier.
            if server['Name'].startswith(server_identifier):
                server_image_name = server['Image']
                # if the image isn't the latest / current version, OR if the server
                # isn't running
                if (self.config['image_replace'] and server_image_name != self.current_image_name) or \
                        server['Status'] != 'ACTIVE':
                    # Then kill it.
                    pass
                    # servers_rm.append(server)
                else:
                    # Otherwise leave it alone.
                    servers_ok.append(server)
        return servers_rm, servers_ok

    def wait_for_state(self, server_name, target_state, escape_states=None, timeout=600):
        """
        Wait for a server to reach a specific state.

        :param str server_name: Name of the server
        :param str target_state: one of https://docs.openstack.org/nova/latest/reference/vm-states.html
        :param list or None escape_states: A list of status that also trigger an exit without hitting the timeout.
        :param int timeout: The maximum number of seconds to wait before exiting.

        :returns: The launched server
        :rtype: novaclient.v2.servers.Server
        """
        if escape_states is None:
            escape_states = []

        slept_for = 0

        # TODO: guard against getting stuck.c
        while True:
            # Get the latest listing of servers
            current_servers = {x['Name']: x for x in self.os_command(['server', 'list'])}
            logging.debug("current_servers: %s", current_servers)
            # If the server is visible + active, let's exit.
            if server_name in current_servers:
                if current_servers[server_name]['Status'] == target_state:
                    return current_servers[server_name]
                elif current_servers[server_name]['Status'] in escape_states:
                    return current_servers[server_name]

            # Sleep
            time.sleep(10)
            slept_for += 10

            if slept_for > timeout:
                return {'Status': 'ERROR', 'Name': server_name}

    def template_config(self, group, is_training=False, cgroups=False, cgroups_args=None, docker_ready=False,
                        gpu_ready=False):
        custom_userdata = copy.copy(self.user_data)
        custom_userdata = re.sub('  GalaxyTraining.*', '  GalaxyTraining = %s' % is_training, custom_userdata)
        custom_userdata = re.sub('  GalaxyGroup.*', '  GalaxyGroup = "%s"' % group, custom_userdata)
        custom_userdata = re.sub('  GalaxyCluster.*', '  GalaxyCluster = "denbi"', custom_userdata)
        custom_userdata = re.sub('  GalaxyDockerHack.*', '  GalaxyDockerHack = %s' % docker_ready, custom_userdata)

        if cgroups:
            custom_userdata = re.sub('# BASE_CGROUP', 'BASE_CGROUP', custom_userdata)
            policy = cgroups_args.get('mem_limit_policy', None)
            if policy:
                custom_userdata = re.sub('# CGROUP_MEMORY_LIMIT_POLICY.*',
                                         'CGROUP_MEMORY_LIMIT_POLICY = {}'.format(policy), custom_userdata)
            size = cgroups_args.get('mem_reserved_size', 1024)
            custom_userdata = re.sub('# RESERVED_MEMORY.*', 'RESERVED_MEMORY = {}'.format(size), custom_userdata)

        if gpu_ready:
            custom_userdata = re.sub('# packages:', 'packages:', custom_userdata)
            custom_userdata = re.sub('# - cuda-10-1', ' - cuda-10-1', custom_userdata)
            custom_userdata = re.sub('# - nvidia-container-toolkit', ' - nvidia-container-toolkit', custom_userdata)
            custom_userdata = re.sub('# use feature : GPUs', 'use feature : GPUs', custom_userdata)
            custom_userdata = re.sub('# GPU_DISCOVERY_EXTRA = -extra', 'GPU_DISCOVERY_EXTRA = -extra', custom_userdata)

        return custom_userdata

    def launch_server(self, name, flavor, group, is_training=False, cgroups=False, cgroups_args=None,
                      docker_ready=False, gpu_ready=False):
        """
        Launch a server with a given name + flavor.

        :returns: The launched server
        :rtype: novaclient.v2.servers.Server
        """
        if self.dry_run:
            return {'Status': 'OK (fake)'}

        logging.info("launching %s (%s)", name, flavor)
        # If it's a compute-something, then we just tag as compute, per current
        # sorting hat expectations.
        custom_userdata = self.template_config(group, is_training=is_training, cgroups=cgroups, cgroups_args=cgroups_args,
                                               docker_ready=docker_ready, gpu_ready=gpu_ready)

        f = tempfile.NamedTemporaryFile(prefix='ensure-enough.', delete=False)
        f.write(custom_userdata.encode())
        f.close()

        args = [
            'server', 'create',
            '--image', self.current_image_name,
            '--flavor', flavor,
            '--key-name', self.config['sshkey'],
            '--availability-zone', 'nova',
            '--nic', 'net-id=%s' % self.config['network'],
            '--user-data', f.name,
        ]

        for sg in self.config['secgroups']:
            args.append('--security-group')
            args.append(sg)

        args.append(name)

        self.os_command(args)

        try:
            os.unlink(f.name)
        except:
            pass

        # Wait for this server to become 'ACTIVE'
        return self.wait_for_state(name, 'ACTIVE', escape_states=['ERROR'])

    def launch_server_volume(self, name, flavor, group, is_training=False, cgroups=False, cgroups_args=None,
                             docker_ready=False, gpu_ready=False,
                             vol_size=12, vol_type='default', vol_boot=False):
        """
        Launch a server with a given name + flavor.

        :returns: The launched server
        :rtype: novaclient.v2.servers.Server
        """
        if self.dry_run:
            return {'Status': 'OK (fake)'}

        logging.info("launching %s (%s) with volume", name, flavor)
        # If it's a compute-something, then we just tag as compute, per current
        # sorting hat expectations.
        custom_userdata = self.template_config(group, is_training=is_training, cgroups=cgroups, cgroups_args=cgroups_args,
                                               docker_ready=docker_ready, gpu_ready=gpu_ready)

        f = tempfile.NamedTemporaryFile(prefix='ensure-enough.', delete=False)
        f.write(custom_userdata.encode())
        f.close()

        args = [
            'boot',
            '--flavor', flavor,
            '--key-name', self.config['sshkey'],
            '--availability-zone', 'nova',
            '--nic', 'net-id=%s' % self.config['network_id'],
            '--user-data', f.name,
            '--security-groups', ','.join(self.config['secgroups']),
        ]
        if vol_boot:
            args.append('--block-device')
            args.append('source=image,id={},dest=volume,size={},volume_type={},bootindex=0,shutdown=remove'.format(self.config['image_id'], vol_size, vol_type))
        else:
            args.append('--image')
            args.append(self.current_image_name)
            args.append('--block-device')
            args.append('source=blank,dest=volume,size={},volume_type={},shutdown=remove'.format(vol_size, vol_type))

        args.append(name)

        self.os_command(args, cmd='nova', is_json=False)

        try:
            os.unlink(f.name)
        except:
            pass

        # Wait for this server to become 'ACTIVE'
        return self.wait_for_state(name, 'ACTIVE', escape_states=['ERROR'])

    def brutally_terminate(self, server):
        if self.dry_run:
            return

        logging.info("Brutally terminating %s", server['Name'])
        logging.info(self.os_command(['server', 'delete', server.get('ID', server['Name'])], is_json=False))

    def gracefully_terminate(self, server, patience=300):
        logging.info("Gracefully terminating %s", server['Name'])

        if self.dry_run:
            return

        if server['Status'] == 'ACTIVE':
            # Get the IP address
            # TODO(hxr): will not support multiply homed
            ip = server['Networks'].split('=')[1]

            time_slept = 0
            while True:
                time.sleep(10)
                time_slept += 10
                if time_slept > patience:
                    logging.info("%s is busy, giving up for this hour.", server['Name'])
                    # exit early
                    return

                # Drain self
                logging.info("executing condor_drain on %s", server['Name'])
                stdout, stderr = self.remote_command(ip, 'condor_drain `hostname -f`')
                logging.info('condor_drain %s %s', stdout, stderr)

                if 'Sent request to drain' in stdout:
                    # Great, we're draining
                    pass
                elif 'Draining already in progress' in stderr:
                    # This one is still draining.
                    pass
                elif "Can't find address" in stderr:
                    # already shut off
                    pass
                else:
                    logging.warn("Something might be wrong: %s, %s", stdout, stderr)
                    break

                try:
                    # Check the status of the machine.
                    stdout, stderr = self.remote_command(ip, 'condor_status | grep slot.*@`hostname -f`')
                    condor_statuses = [x.split()[4] for x in stdout.strip().split('\n')]
                except IndexError:
                    break

                logging.info('condor_status %s', condor_statuses)
                # if 'Retiring' then we're still draining. If 'Idle' then safe to exit.
                if len(condor_statuses) > 1:
                    # The machine is currently busy but will not accept any new jobs. For now, leave it alone.
                    logging.info("%s is busy, sleeping.", server['Name'])
                    continue
                else:
                    # Ensure we are promptly removed from the pool
                    stdout, stderr = self.remote_command(ip, '/usr/sbin/condor_off -graceful `hostname -f`')
                    logging.info('/usr/sbin/condor_off %s %s', stdout, stderr)

        # The image is completely drained so we're safe to kill.
        logging.info(self.os_command(['server', 'delete', server['ID']], is_json=False))

        # We'll wait a bit until the server is gone.
        while True:
            # Get the latest listing of servers
            current_servers = [x['Name'] for x in self.os_command(['server', 'list'])]
            # If the server is no longer visible, let's exit.
            if server['Name'] not in current_servers:
                break
            time.sleep(10)

    def top_up(self, desired_instances, prefix, flavor, group, volume=False, volume_args=None,
               cgroups=False, cgroups_args=None, docker_ready=False, gpu_ready=False):
        """
        :param int desired_instances: Number of instances of this type to launch

        :param str prefix: Something like `vgcnbwc-{resource_id}`

        :param str resource_identifier: Just the `{resource_id}` from previous part

        :param str flavor: flavor to launch

        :param str group: The group that it is launched in (compute, upload, training-{resource_id})
        """
        # Fetch the CURRENT state.
        tmp_servers_rm, tmp_servers_ok = self.identify_server_group(prefix)
        # Get all together
        all_servers = tmp_servers_rm + tmp_servers_ok
        # Because we care not about how many are currently ok, but the number of
        # ACTIVE servers that can be processing jobs.
        num_active = [x['Status'] == 'ACTIVE' for x in all_servers]
        # Now we know the difference that we need to launch.
        to_add = max(0, desired_instances - len(num_active))
        for i in range(to_add):
            args = (
                self.non_conflicting_name(prefix, all_servers),
                flavor,
                group,
            )

            kwargs = {
                'is_training': 'training' in prefix,
                'cgroups': cgroups,
                'cgroups_args': cgroups_args,
                'docker_ready': docker_ready,
                'gpu_ready': gpu_ready,
            }

            if volume:
                kwargs['vol_size'] = volume_args.get('size', 12)
                kwargs['vol_type'] = volume_args.get('type', 'default')
                kwargs['vol_boot'] = volume_args.get('boot', False)
                server = self.launch_server_volume(*args, **kwargs)
            else:
                server = self.launch_server(*args, **kwargs)

            if server['Status'] == 'ERROR':
                if 'ID' in server:
                    fault = self.os_command(['server', 'show', server['ID']]).get('fault', {'message': '<error>'})
                else:
                    fault = {'message': "Unknown"}
                logging.error('Failed to launch %s: %s', server['Name'], fault['message'])
                self.brutally_terminate(server)
            else:
                logging.info('Launched. %s (state=%s)', server, server['Status'])

    def syncronize_infrastructure(self):
        # Now we process our different resources.
        for resource_identifier in self.config['deployment']:
            resource = self.config['deployment'][resource_identifier]
            # The server names are constructed as:
            #    vgcnbwc-{id}
            prefix = 'vgcnbwc-' + resource_identifier
            logging.info("Processing %s" % prefix)
            # Image flavor
            flavor = resource['flavor']
            desired_instances = resource['count']

            # Count the number of existing VMs of this resource group
            servers_rm, servers_ok = self.identify_server_group(prefix)

            # If we have more servers allocated than desired, we should remove some.
            if len(servers_ok) > desired_instances:
                difference = len(servers_ok) - desired_instances
                # Take the first `difference` number of servers.
                servers_rm += servers_ok[0:difference]
                # And slice the ok list as well.
                servers_ok = servers_ok[difference:]

            # If the resource has a `start` or `end` and we are not within that range,
            # then we should move all resources from `servers_ok` to `servers_rm`
            if 'end' in resource and self.today > resource['end']:
                servers_rm = servers_ok
                servers_ok = []
                desired_instances = 0
            elif 'start' in resource and self.today < resource['start']:
                servers_rm = servers_ok
                servers_ok = []
                desired_instances = 0

            logging.info("Found %s/%s running, %s to remove", len(servers_ok), desired_instances, len(servers_rm))

            # Ok, here we possibly have some that need to be removed, and possibly have
            # some number that need to be added (of the new image version)

            # We don't want to abuse resources and we'd like to keep within the
            # limited number of VMs to make this more reusable. If we say "max 10 VMs"
            # we should honor that.

            # We will start expiring old ones, "topping up" as we go along.
            for server in servers_rm:
                # we need to SSH in and condor_drain, wait for queue to empty, and then
                # kill.

                # Galaxy-net must be the used network, maybe this check is extraneous
                # but better to only work on things we know are safe to work on.
                netz = [x.split('=')[0] for x in server['Networks'].split(',')]
                if self.config['network'] not in netz:
                    if server['Status'] == 'ERROR':
                        self.brutally_terminate(server)
                        continue

                    logging.warn(server['Networks'])
                    logging.warn("Not sure how to handle server %s", server['Name'])
                    continue

                # Gracefully (or violently, depending on patience) terminate the VM.
                if self.config['graceful']:
                    try:
                        self.gracefully_terminate(server)
                    except paramiko.ssh_exception.NoValidConnectionsError:
                        # If we can't connect, just skip it.
                        logging.warning("Could not kill %s", server['Name'])
                        pass
                else:
                    self.brutally_terminate(server)

                # With that done, 'top up' to the correct number of VMs.
                self.top_up(desired_instances, prefix, flavor,
                            resource.get('group', resource_identifier),
                            volume=True if 'volume' in resource else False,
                            volume_args=resource.get('volume', None),
                            cgroups=True if 'cgroups' in resource else False,
                            cgroups_args=resource.get('cgroups', None),
                            docker_ready=resource.get('docker_ready', False),
                            gpu_ready=resource.get('gpu_ready', False))

            # Now that we've removed all that we need to remove, again, try to top-up
            # to make sure we're OK. (Also important in case we had no servers already
            # running.)
            self.top_up(desired_instances, prefix, flavor,
                        resource.get('group', resource_identifier),
                        volume=True if 'volume' in resource else False,
                        volume_args=resource.get('volume', None),
                        cgroups=True if 'cgroups' in resource else False,
                        cgroups_args=resource.get('cgroups', None),
                        docker_ready=resource.get('docker_ready', False),
                        gpu_ready=resource.get('gpu_ready', False))


def make_parser():
    parser = argparse.ArgumentParser(prog="ensure_enough",
                                     description='VGCN Infrastructure Management')
    parser.add_argument('-r', '--resources_file', type=str, metavar='PATH',
                        help='Resources file', default='resources.yaml')
    parser.add_argument('-u', '--userdata_file', type=str, metavar='PATH',
                        help='Userdata file', default='userdata.yaml')
    parser.add_argument('-d', '--dry_run', action='store_true',
                        help='dry run mode')

    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = parser.parse_args()

    s = StateManagement(args=args)
    s.syncronize_infrastructure()
