#!/usr/bin/env python
import datetime
import os
import paramiko
import random
import time
import yaml

from keystoneauth1 import loading
from keystoneauth1 import session
from novaclient import client as nova_client
from glanceclient import client as glance_client

loader = loading.get_plugin_loader('password')
auth = loader.load_from_options(auth_url=os.environ['OS_AUTH_URL'],
                                username=os.environ['OS_USERNAME'],
                                password=os.environ['OS_PASSWORD'],
                                project_id=os.environ['OS_TENANT_ID'])
sess = session.Session(auth=auth)
nova = nova_client.Client('2.0', session=sess)
glance = glance_client.Client('2', session=sess)

with open('resources.yaml', 'r') as handle:
    DATA = yaml.load(handle)

# These are hard-coded values.
SSHKEY = 'cloud2'
NETWORK = [network for network in nova.networks.list()
           if network.human_id == 'galaxy-net'][0]
SECGROUPS = ['ufr-only-v2']
# And some maps of human-name:object
FLAVORS = {flavor.name: flavor for flavor in nova.flavors.list()}
IMAGES = {image.name: image for image in glance.images.list()}
# Grab the 'latest' image name.
CURRENT_IMAGE_NAME = DATA['image']
CURRENT_IMAGE = IMAGES[CURRENT_IMAGE_NAME]
VGCN_PUBKEYS = DATA['pubkeys']
TODAY = datetime.date.today()


class VgcnPolicy(paramiko.client.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        """Custom policy that only accepts known VGCN public key(s)"""
        if key.get_base64() not in VGCN_PUBKEYS:
            raise Exception("Untrusted Host")


def remote_command(hostname, command, username='centos', port=22):
    k = paramiko.RSAKey.from_private_key_file("/home/hxr/.ssh/keys/id_rsa_cloud2")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(VgcnPolicy)
    print("Connecting to %s@%s:%s" % (username, hostname, port))
    client.connect(hostname, port=port, username=username, pkey=k)

    stdin, stdout, stderr = client.exec_command(command)
    # Returned as 'bytes' in py3k
    stdout_decoded = stdout.read().decode('utf-8')
    stderr_decoded = stderr.read().decode('utf-8')
    return stdout_decoded, stderr_decoded


def non_conflicting_name(prefix, existing_servers):
    """
    Generate a name for the machine that's unique to the machine and not used
    by any existing ones.

    :param str prefix: the name prefix, usually vgcnbwc-{tag}
    :param list(Nova) existing_servers: list of existing servers against which
                                        we will check the names.
    """
    server_names = [x.name for x in existing_servers]
    # Make at least ten tries
    for i in range(10):
        # generate a test name, similar style to jenkins images.
        test_name = '%s-%04d' % (prefix, random.randint(0, 10000))
        # If unused, we can use this.
        if test_name not in server_names:
            return test_name

    # Generate a failsafe name to ensure deterministic exiting.
    return '%s-%f' % (prefix, time.time())


def identify_server_group(server_identifier):
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
    for server in nova.servers.list():
        # Filter by those with our prefix.
        if server.name.startswith(prefix):
            server_image_name = glance.images.get(server.image['id'])['name']
            # if the image isn't the latest / current version, OR if the server
            # isn't running
            if server_image_name != CURRENT_IMAGE_NAME or \
                    server.status != 'ACTIVE':
                # Then kill it.
                servers_rm.append(server)
            else:
                # Otherwise leave it alone.
                servers_ok.append(server)
    return servers_rm, servers_ok


def wait_for_state(server_name, target_state):
    """
    Wait for a server to reach a specific state.

    :param str server_name: Name of the server
    :param str target_state: one of https://docs.openstack.org/nova/latest/reference/vm-states.html

    :rtype: None
    """
    # TODO: guard against getting stuck.c
    while True:
        # Get the latest listing of servers
        current_servers = {x.name: x for x in nova.servers.list()}
        # If the server is visible + active, let's exit.
        if server_name in current_servers and current_servers[server_name].status == target_state:
            break
        time.sleep(10)


def launch_server(name, flavor):
    print(nova.servers.create(
        name=name,
        image=CURRENT_IMAGE,
        flavor=flavor,
        key_name=SSHKEY,
        availability_zone='nova',
        security_groups=SECGROUPS,
        nics=[{'net-id': NETWORK.id}],
    ))

    # Wait for this server to become 'ACTIVE'
    wait_for_state(name, 'ACTIVE')


def gracefully_terminate(server):
    # Get the IP address in galaxy-net
    ip = server.networks['galaxy-net'][0]

    if server.status == 'ACTIVE':
        # Drain self
        stdout, stderr = remote_command(ip, 'condor_drain `hostname -f`')

        if 'Sent request to drain' not in stdout:
            print("Something might be wrong: %s, %s" % (stdout, stderr))

        have_slept = 0
        while True:
            # Check the status of the machine.
            stdout, stderr = remote_command(ip, 'condor_status | grep slot1@`hostname -f`')
            # if 'Retiring' then we're still draining. If 'Idle' then safe to exit.
            if 'Idle' in stdout:
                # Safe to kill.
                break
            else:
                time.sleep(10)
                have_slept += 10

            # At some point we give up.
            if have_slept > DATA['patience']:
                break

    # The image is completely drained so we're safe to kill.
    print(nova.servers.delete(server))

    # We'll wait a bit until the server is gone.
    while True:
        # Get the latest listing of servers
        current_servers = [x.name for x in nova.servers.list()]
        # If the server is no longer visible, let's exit.
        if server.name not in current_servers:
            break
        time.sleep(10)


def top_up(desired_instances, prefix, flavor):
    # Fetch the CURRENT state.
    tmp_servers_rm, tmp_servers_ok = identify_server_group(prefix)
    # Get all together
    all_servers = tmp_servers_rm + tmp_servers_ok
    # Because we care not about how many are currenlty ok, but the number of
    # ACTIVE servers that can be processing jobs.
    num_active = [x.state == 'ACTIVE' for x in all_servers]
    # Now we know the difference that we need to launch.
    to_add = max(0, desired_instances - num_active)
    for i in range(to_add):
        launch_server(non_conflicting_name(prefix, all_servers), flavor)


# Now we process our different resources.
for resource_identifier in DATA['deployment']:
    resource = DATA['deployment'][resource_identifier]
    # The server names are constructed as:
    #    vgcnbwc-compute-{number}
    #    vgcnbwc-upload-{number}
    #    vgcnbwc-metadata-{number}
    #    vgcnbwc-training-{training_identifier}-{number}
    prefix = 'vgcnbwc-' + resource['tag']
    print("Processing %s" % prefix)
    # Image flavor
    flavor = FLAVORS[resource['flavor']]
    desired_instances = resource['count']

    # Count the number of existing VMs of this resource group
    servers_rm, servers_ok = identify_server_group(prefix)

    # If we have more servers allocated than desired, we should remove some.
    if len(servers_ok) > desired_instances:
        difference = len(servers_ok) - desired_instances
        # Take the first `difference` number of servers.
        servers_rm += servers_ok[0:difference]
        # And slice the ok list as well.
        servers_ok = servers_ok[difference:]

    # If the resource has a `start` or `end` and we are not within that range,
    # then we should move all resources from `servers_ok` to `servers_rm`
    if 'end' in resource and TODAY > resource['end']:
        servers_rm = servers_ok
        servers_ok = []
        desired_instances = 0
    elif 'start' in resource and TODAY < resource['start']:
        servers_rm = servers_ok
        servers_ok = []
        desired_instances = 0

    print("Found %s/%s running, %s to remove" %
          (len(servers_ok), desired_instances, len(servers_rm)))

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
        if 'galaxy-net' not in server.networks:
            print(server.networks)
            print("Not sure how to handle server %s" % server.name)
            continue

        # Gracefully (or violently, depending on patience) terminate the VM.
        gracefully_terminate(server)

        # With that done, 'top up' to the correct number of VMs.
        top_up(desired_instances, prefix, flavor)

    # Now that we've removed all that we need to remove, again, try to top-up
    # to make sure we're OK. (Also important in case we had no servers already
    # running.)
    top_up(desired_instances, prefix, flavor)
