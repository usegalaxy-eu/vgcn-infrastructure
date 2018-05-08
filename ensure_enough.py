#!/usr/bin/env python
import datetime
import os
import paramiko
import random
import time
import yaml
import logging

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

# These are hard-coded values.
SSHKEY = 'cloud2'
NETWORK = [network for network in nova.networks.list()
           if network.human_id == 'galaxy-net'][0]
SECGROUPS = ['ufr-only-v2']
# And some maps of human-name:object
FLAVORS = {flavor.name: flavor for flavor in nova.flavors.list()}
IMAGES = {image.name: image for image in glance.images.list()}
# Grab the 'latest' image name.
CURRENT_IMAGE_NAME = None  # DATA['image']
CURRENT_IMAGE = None  # IMAGES[CURRENT_IMAGE_NAME]
VGCN_PUBKEYS = None  # DATA['pubkeys']
TODAY = datetime.date.today()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
# Maximum number of allocatable names. After which it will switch to time.time()
MAX_SERVER_POOL = 10000
USER_DATA = open('userdata.yml', 'r').read()


class VgcnPolicy(paramiko.client.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        """Custom policy that only accepts known VGCN public key(s)"""
        if key.get_base64() not in VGCN_PUBKEYS:
            raise Exception("Untrusted Host")


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


def non_conflicting_name(prefix, existing_servers):
    """
    Generate a name for the machine that's unique to the machine and not used
    by any existing ones.

    :param str prefix: the name prefix, usually vgcnbwc-{resource_identifier}
    :param list(Nova) existing_servers: list of existing servers against which
                                        we will check the names.
    """
    server_names = [x.name for x in existing_servers]
    # Make at least ten tries
    for i in range(10):
        # generate a test name, similar style to jenkins images.
        test_name = '%s-%04d' % (prefix, random.randint(0, MAX_SERVER_POOL))
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
        # Filter by those with our server_identifier.
        if server.name.startswith(server_identifier):
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


def wait_for_state(server_name, target_state, escape_states=None, timeout=600):
    """
    Wait for a server to reach a specific state.

    :param str server_name: Name of the server
    :param str target_state: one of https://docs.openstack.org/nova/latest/reference/vm-states.html
    :param list or None escape_states: A list of status that also trigger an exit without hitting the timeout.
    :param int timeout: The maximum number of seconds to wait before exiting.

    :returns: The launched server.
    :rtype: novaclient.v2.servers.Server
    """
    if escape_states is None:
        escape_states = []

    slept_for = 0

    # TODO: guard against getting stuck.c
    while True:
        # Get the latest listing of servers
        current_servers = {x.name: x for x in nova.servers.list()}
        logging.debug("current_servers: %s", current_servers)
        # If the server is visible + active, let's exit.
        if server_name in current_servers:
            if current_servers[server_name].status == target_state:
                return current_servers[server_name]
            elif current_servers[server_name].status in escape_states:
                return current_servers[server_name]

        # Sleep
        time.sleep(10)
        slept_for += 10

        if slept_for > timeout:
            return current_servers[server_name]


def launch_server(name, flavor):
    """
    Launch a server with a given name + flavor.

    :returns: The launched server.
    :rtype: novaclient.v2.servers.Server
    """
    logging.info("launching %s (%s)", name, flavor)
    nova.servers.create(
        name=name,
        image=CURRENT_IMAGE,
        flavor=flavor,
        key_name=SSHKEY,
        availability_zone='nova',
        security_groups=SECGROUPS,
        nics=[{'net-id': NETWORK.id}],
        userdata=USER_DATA,
    )

    # Wait for this server to become 'ACTIVE'
    return wait_for_state(name, 'ACTIVE', escape_states=['ERROR'])


def gracefully_terminate(server):
    log.info("Gracefully terminating %s", server.name)

    if server.status == 'ACTIVE':
        # Get the IP address in galaxy-net
        ip = server.networks['galaxy-net'][0]

        # Drain self
        log.info("executing condor_drain on %s", server.name)
        stdout, stderr = remote_command(ip, 'condor_drain `hostname -f`')
        log.info('condor_drain %s %s', stdout, stderr)

        if 'Sent request to drain' in stdout:
            # Great, we're draining
            return
        elif 'Draining already in progress' in stderr:
            # This one is still draining.
            log.info("Already draining")
        else:
            log.warn("Something might be wrong: %s, %s", stdout, stderr)

        # Check the status of the machine.
        stdout, stderr = remote_command(ip, 'condor_status | grep slot.*@`hostname -f`')
        condor_statuses = [x.split()[4] for x in stdout.strip().split('\n')]
        log.info('condor_status %s', condor_statuses)
        # if 'Retiring' then we're still draining. If 'Idle' then safe to exit.
        if len(condor_statuses) > 1:
            # The machine is currently busy but will not accept any new jobs. For now, leave it alone.
            log.info("%s is busy, leaving it alone until next hour." % server.name)
            return

        # Ensure we are promptly removed from the pool
        stdout, stderr = remote_command(ip, '/usr/sbin/condor_off -graceful `hostname -f`')
        log.info('/usr/sbin/condor_off %s %s', stdout, stderr)

    # The image is completely drained so we're safe to kill.
    log.info(nova.servers.delete(server))

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
    num_active = [x.status == 'ACTIVE' for x in all_servers]
    # Now we know the difference that we need to launch.
    to_add = max(0, desired_instances - len(num_active))
    for i in range(to_add):
        server = launch_server(non_conflicting_name(prefix, all_servers), flavor)
        if server.status == 'ERROR':
            log.info('Failed to launch, removing. %s (state=%s)', server, server.status)
            print(server)
            print(server.to_dict())
            gracefully_terminate(server)
        else:
            log.info('Launched. %s (state=%s)', server, server.status)


def syncronize_infrastructure(DATA):
    # Now we process our different resources.
    for resource_identifier in DATA['deployment']:
        resource = DATA['deployment'][resource_identifier]
        # The server names are constructed as:
        #    vgcnbwc-compute-{number}
        #    vgcnbwc-upload-{number}
        #    vgcnbwc-metadata-{number}
        #    vgcnbwc-training-{training_identifier}-{number}
        prefix = 'vgcnbwc-' + resource_identifier
        log.info("Processing %s" % prefix)
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

        log.info("Found %s/%s running, %s to remove", len(servers_ok),
                 desired_instances, len(servers_rm))

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
                if server.status == 'ERROR':
                    gracefully_terminate(server)
                    continue

                log.warn(server.networks)
                log.warn("Not sure how to handle server %s", server.name)
                continue

            # Gracefully (or violently, depending on patience) terminate the VM.
            try:
                gracefully_terminate(server)
            except paramiko.ssh_exception.NoValidConnectionsError:
                # If we can't connect, just skip it.
                log.warning("Could not kill %s", server.name)
                pass

            # With that done, 'top up' to the correct number of VMs.
            top_up(desired_instances, prefix, flavor)

        # Now that we've removed all that we need to remove, again, try to top-up
        # to make sure we're OK. (Also important in case we had no servers already
        # running.)
        top_up(desired_instances, prefix, flavor)


def main():
    global CURRENT_IMAGE_NAME
    global CURRENT_IMAGE
    global VGCN_PUBKEYS

    with open('resources.yaml', 'r') as handle:
        DATA = yaml.load(handle)

    CURRENT_IMAGE_NAME = DATA['image']
    CURRENT_IMAGE = IMAGES[CURRENT_IMAGE_NAME]
    VGCN_PUBKEYS = DATA['pubkeys']
    syncronize_infrastructure(DATA)


if __name__ == '__main__':
    main()
