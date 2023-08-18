#!/usr/bin/env python
"""Keeps the state of de.NBI-cloud in sync with the resource definition.

Keeps the state of de.NBI-cloud in sync with the resource definition provided
in `resources.yaml`.
"""

import argparse
import concurrent.futures
import datetime
import io
import logging
import socket
import time
from base64 import b64encode
from functools import reduce
from multiprocessing import Process
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)
from uuid import UUID

import openstack
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from openstack.compute.v2.server import Server
from openstack.connection import Connection
from paramiko import SSHClient
from paramiko.client import AutoAddPolicy
from paramiko.file import BufferedFile
from paramiko.ssh_exception import NoValidConnectionsError, SSHException

# server names are constructed as
#   vgcnbwc-{group_identifier}-{unique_id}
PREFIX: str = "vgcnbwc-"

SSH_USERNAME: str = "centos"
SSH_PORT: int = 22

logging.basicConfig(level=logging.INFO)


def print_stream(
    stream: BufferedFile,
    print_function: Callable[[bytes], Any] = print,
    save: bool = True,
) -> Optional[bytes]:
    """Print a byte stream in real time, optionally returning it afterward.

    Args:
        stream: Binary stream to print.
        print_function: Function to call to print the lines of the stream.
        save: Whether to return a copy of the contents of the stream.

    Returns:
        If `save` is set to `True`, a bytes object containing a copy of the
        contents of the stream.
    """
    stream_copy = io.BytesIO()
    for line in stream:
        if isinstance(line, str):
            line = line.encode("utf-8")
        print_function(line)
        if save:
            stream_copy.write(line)
    stream_copy.seek(0)
    return stream_copy.read() if save else None


def print_streams(
    streams: Sequence[BufferedFile],
    print_functions: Sequence[Callable[[bytes], Any]] = tuple(),
    save: Sequence[bool] = tuple(),
) -> List[Optional[bytes]]:
    """Print multiple byte streams in real time and concurrently.

     Print byte streams in real time and concurrently, optionally returning
     them afterward.

     Args:
         streams: Sequence of binary streams to print.
         print_functions: Sequence of functions to call to print each stream.
            For example, it may make sense to print one stream to stdout,
            another to stderr, and run a third one through the logging system.
        save: Whether to return a copy of the contents of the streams.

    Returns:
        If `save` is set to `True`, a sequence of bytes objects containing
        copies of the contents of the streams.
    """
    print_functions = print_functions or [print] * len(streams)
    save = save or [True] * len(streams)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(streams)
    ) as executor:
        futures = [
            executor.submit(
                print_stream, stream, print_function=function, save=save_stream
            )
            for stream, function, save_stream in zip(
                streams, print_functions, save
            )
        ]
        outputs = [future.result() for future in futures]

    return outputs


class RemoteCommandError(RuntimeError):
    """Raised when a remote command fails to run.

    Raised by the function `remote_command` when the remote command execution
    fails.
    """

    stdout: bytes
    stderr: bytes
    exit_code: int

    def __init__(
        self, text: str, stdout: bytes, stderr: bytes, exit_code: int
    ):
        """Initialize a new RemoteCommandError exception."""
        super().__init__(text)
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


def remote_command(
    command: str,
    client: SSHClient,
    log: bool = True,
) -> Tuple[bytes, bytes]:
    """Run a command in a remote server using SSH.

    Run a command in a remote server using SSH. Return after the command has
    exited.

    Args:
        command: Command to run.
        client: SSH client already connected to the server.
        log: Whether to print the command and its outputs (stdout and stderr)
            in real time. Outputs are printed using the Python's logging
            framework using DEBUG as log level. The command itself is logged
            using INFO as log level.

    Returns:
        Standard output and standard error.

    Raises:
        RuntimeError: The command's exit code was different from zero. The
            standard error, standard output and exit code are attached to the
            exception as the `stdout`, `stderr` and `exit_code` attributes.
    """
    if log:
        logging.info(f"Remote SSH command: {command}")

    stdin, stdout, stderr = client.exec_command(command)
    channel = stderr.channel
    if log:
        stdout, stderr = print_streams(
            (stdout, stderr),
            print_functions=(
                lambda line: logging.debug(line.decode("utf-8")),
                lambda line: logging.debug(line.decode("utf-8")),
            ),
            save=(True, True),
        )
    else:
        stdout = stdout.read()
        stderr = stderr.read()
    exit_code = channel.recv_exit_status()

    if exit_code:
        error = RemoteCommandError(
            f"Command {command} exited with code {exit_code}.",
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
        raise error

    return stdout, stderr


def unique_name(prefix: str, existing_names: Set[str] = None) -> str:
    """Generate a unique name for a virtual machine.

    Generate a name for a virtual machine that is not already in use by any
    existing ones.

    The name is constructed by appending`-XXXX` to a given prefix, where `XXXX`
    is a left zero-padded random integer between 0000 and 9999. Names matching
    any name provided in the set `existing_names` are discarded.

    Args:
        prefix: Prefix for constructing names.
        existing_names: List of existing server names to be avoided.

    Returns:
        Unique name constructed from the given prefix and a random integer.

    Raises:
        ValueError: All names that this function can generate are already
            taken.
    """
    existing_names = existing_names or set()
    start, end = 0, 10000

    for i in range(start, end):
        name = f"{prefix}-{i:04d}"
        if name not in existing_names:
            break
    else:
        raise ValueError(
            f"Cannot generate a unique name: all names between "
            f"{prefix}-{start:04d} and {prefix}-{end:04d} are in use."
        )

    return name


def get_ssh_access_address(
    client: SSHClient,
    server: Mapping,
    port: int = SSH_PORT,
    username: str = SSH_USERNAME,
    *args,
    **kwargs,
) -> str:
    """Determine an ip address where an OpenStack server is reachable via SSH.

    Servers can have multiple network interfaces and thus possess several ip
    addresses. This function tries to ssh all of them to find one where the
    server is reachable from the host this function is running on.

    Args:
        client: Paramiko SSH client instance.
        server: Mapping with structure analogous to that of OpenStack `Server`
            objects.
        port: Port to use for SSH connections.
        username: Username to use for SSH connections.
        args: Any extra arguments to pass to `SSHClient.connect`.
        kwargs: Any extra keyword arguments to pass to `SSHClient.connect`.

    Returns:
        An IP address where log-in via SSH is possible.

    Raises:
        RuntimeError: No successful SSH log-in on any of the server's IP
            addresses.
    """
    ips = {
        address["addr"]
        for network, addresses in server["addresses"].items()
        for address in addresses
    }

    for ip in ips:
        try:
            client.connect(
                ip,
                port=port,
                username=username,
                *args,
                **kwargs,
                allow_agent=False,
                look_for_keys=False,
            )
        except socket.error as exception:
            logging.warning(exception, exc_info=True)
        except SSHException as exception:
            logging.warning(exception, exc_info=True)
        else:
            return ip
    else:
        raise RuntimeError(f"Unable to gain ssh access to {server['name']}.")


def condor_drain(
    client: SSHClient,
) -> None:
    """Run `condor_drain` on a server.

    Args:
        client: Paramiko SSH client already connected to the server.

    Raises:
        RuntimeError: Unexpected `condor_drain` output.
    """
    command = "condor_drain `hostname -f`"

    try:
        stdout, stderr = remote_command(command, client, log=False)
    except RemoteCommandError as exception:
        stdout = exception.stdout.decode("utf-8")
        stderr = exception.stderr.decode("utf-8")

    if not any(
        (
            b"Sent request to drain" in stdout,
            b"Draining already in progress" in stderr,
            b"Can't find address" in stderr,
        )
    ):
        raise RuntimeError("Unexpected output from condor_drain.")


def condor_active(
    client: SSHClient,
) -> bool:
    """Check the status of the instance of Condor running on the server.

    Args:
        client: SSH client already connected to the server.

    Returns:
        Whether Condor is active or not.
    """
    command = "condor_status | grep slot.*@`hostname -f`"

    try:
        stdout, stderr = remote_command(command, client, log=False)
        stdout = stdout.decode("utf-8")
    except RemoteCommandError as exception:
        stdout = exception.stdout.decode("utf-8")

    try:
        condor_statuses = [x.split()[4] for x in stdout.strip().split("\n")]
    except IndexError:
        condor_statuses = []

    active = len(condor_statuses) > 1

    return active


def condor_off(
    client: SSHClient,
) -> None:
    """Run `condor_off` on a server.

    Run `condor_off` to ensure we are promptly removed from the pool.

    Args:
        client: SSH client already connected to the server.
    """
    command = "/usr/sbin/condor_off -graceful `hostname -f`"

    remote_command(command, client, log=False)


class CondorShutdownException(RuntimeError):
    """Raised when HTCondor cannot be shutdown gracefully.

    Raised by the function `condor_graceful_shutdown` when HTCondor cannot be
    shutdown gracefully.
    """


def condor_graceful_shutdown(
    client: SSHClient,
    timeout: int = 300,
    interval: int = 10,
) -> None:
    """Shut down Condor gracefully on a server.

    Attempt to shut down Condor gracefully on a server. This function will run
    `condor_drain` and `condor_status` periodically on a server until it has
    been drained. After that, it will run `condor_off`.

    Args:
        client: SSH client already connected to the server.
        timeout: Minimum amount of time for which the function will attempt to
            shut down condor. The function will exit as soon as the OS hands
            the control back to it. This implies that it can run for longer
            than this timeout.
        interval: Time interval between attempts to stop HTCondor.

    Raises:
        CondorShutdownException: HTCondor remained active for at least
            `timeout` seconds.
    """
    active = True

    start = time.time()
    current = time.time()
    while active and current - start < timeout:
        condor_drain(client)
        active = condor_active(client)
        time.sleep(max(float(0), interval - (time.time() - current)))
        current = time.time()

    if active:
        raise CondorShutdownException(
            f"Could not gracefully stop HTCondor after"
            f"{current - start:.0f} seconds."
        )

    condor_off(client)


def gracefully_terminate(
    server: Mapping,
    cloud: Connection,
    timeout: int = 300,
) -> None:
    """Delete a server gracefully.

    Attempt to shut down Condor on a server, then remove the server.

    Args:
        server: Mapping with structure analogous to that of OpenStack `Server`
            objects.
        cloud: OpenStack Connection object connected to the server's cloud.
        timeout: Maximum time to wait for Condor to be shut down before
            removing the server.

    Raises:
        CondorShutdownException: Condor could not be shut down after `timeout`
            seconds.
    """
    logging.debug(f"Gracefully terminating {server['name']}...")

    if server["status"] == "ACTIVE":
        client = SSHClient()

        # do not verify the host key: no private information is sent
        client.set_missing_host_key_policy(AutoAddPolicy)

        ip = get_ssh_access_address(client, server)

        client.connect(ip, port=SSH_PORT, username=SSH_USERNAME)
        shutdown_process = Process(
            target=lambda: condor_graceful_shutdown(client, timeout=timeout)
        )
        shutdown_process.run()
        shutdown_process.join(timeout=timeout)

        if shutdown_process.exitcode is None:
            raise CondorShutdownException(
                f"HTCondor shutdown timed out after {timeout} seconds."
            )

        shutdown_process.terminate()

    # remove server
    delete_and_wait(server, cloud)


def compute_increment(
    group_config: Mapping,
    status: int,
) -> int:
    """Compute the changes needed to synchronize a single resource group.

    Compute the amount of servers to spawn or to remove in order to
    synchronize a single resource group.

    If the group has a start or end date and the current date is not
    within that range, then all servers should be deleted.

    Args:
        group_config: Mapping containing only the configuration for the
            resource group being processed.
        status: Amount of servers that currently belong to the group.

    Returns:
        Amount of servers to spawn (positive) or remove (negative). Zero means
        no servers need to be spawned nor removed.
    """
    today = datetime.date.today()
    date_range_is_valid = (
        group_config.get("start", today)
        <= today
        <= group_config.get("end", today)
    )
    return group_config["count"] - status if date_range_is_valid else -status


def filter_incorrect_images(
    servers: List[Mapping],
    config: Mapping,
    group_config: Mapping,
    cloud: Connection,
) -> List[Mapping]:
    """Filter existing servers running an incorrect image.

    Filter existing servers running an image that does not match the one
    defined in their resource group.

    Args:
        servers: A list of mappings, with structure analogous to that of
            OpenStack `Server` objects, to apply the filter to.
        config: Mapping containing the (whole) resource definition from
            `resources.yaml`.
        group_config: Mapping containing only the configuration for the
            resource group being processed.
        cloud: OpenStack connection object.

    Returns:
        The servers running an image that does not match the one defined in
        their resource group.
    """
    image = config["images"][group_config.get("image", "default")]
    try:
        UUID(hex=image)
    except ValueError:  # find image by name
        image = cloud.compute.find_image(image)["id"]

    return [
        server
        for server in servers
        if server["image"]["id"] is not None  # excludes servers using volumes
        and server["image"]["id"] != image
    ]


def remove_server(server: Server, config: dict, cloud: Connection) -> None:
    """Remove a server.

    Args:
        config: Mapping containing the (whole) resource definition from
            `resources.yaml`.
        server: OpenStack server to be removed.
        cloud: OpenStack connection object.
    """
    graceful = config["graceful"]

    if graceful:
        try:
            gracefully_terminate(server, cloud=cloud)
        except NoValidConnectionsError:
            logging.warning(
                f"Could not gracefully terminate {server['name']}."
            )
    else:
        delete_and_wait(server, cloud)


def template_userdata(
    name: str,
    config: Mapping,
    group_config: Mapping,
    user_data_file: Path,
    vars_files: Iterable[Path] = frozenset(),
) -> str:
    """Render the cloud-init's user data file template.

    Newly spawned servers are passed a user data file to be processed by
    cloud-init on the first run of the server. Such file is constructed by this
    function from a Jinja template.

    The resource definition (e.g. `resources.yaml`), the server group
    configuration and optionally the contents of any extra YAML files are
    passed as variables to Jinja for rendering the template.

    Args:
        name: Instance name in OpenStack.
        config: Mapping containing the (whole) resource definition from
            `resources.yaml`. It is used to read the default values
            (group-independent). Thus, the "deployment" key can optionally be
            stripped.
        group_config: Mapping containing only the configuration for the
            resource group being processed.
        user_data_file: Path of the Jinja template for the user data file.
        vars_files: Path of YAML files with extra variables to be used while
            rendering the template.
    """
    vars_files = frozenset(vars_files)
    vars_from_files = (
        reduce(
            lambda x, y: x.update(y),
            (yaml.safe_load(open(file, "r")) for file in vars_files),
        )
        if vars_files
        else {}
    )

    environment = Environment(
        loader=FileSystemLoader(user_data_file.parent),
        undefined=StrictUndefined,
    )
    template = environment.get_template(
        user_data_file.name,
    )

    return template.render(
        name=name,
        **config,
        **group_config,
        **vars_from_files,
    )


def wait_for_state(
    server: Mapping,
    target_states: Set[Union[str, None]],
    cloud: Connection,
    timeout: int = 600,
    interval: int = 10,
) -> Server:
    """Wait for a server to reach specific states.

    Args:
        server: OpenStack `Server` object (which is an instance of a Mapping).
        target_states: A set of strings from
            https://docs.openstack.org/nova/latest/reference/vm-states.html.
            In addition, the state `None` is also accepted and stands for the
            server no longer being listed in OpenStack.
        cloud: OpenStack Connection object.
        timeout: The maximum number of seconds to wait before exiting.
        interval: Time between requests to OpenStack.

    Raises:
        RuntimeError: The server did not reach any of the target states.

    Returns:
        The server in its target status.
    """
    start = time.time()
    while time.time() - start < timeout:
        server = cloud.compute.find_server(server["id"])

        if (server["status"] if server is not None else None) in target_states:
            return server

        time.sleep(interval)

    raise RuntimeError(
        f"Server {server['name']} did not reach any of the target states"
        f"({', '.join(target_states)}) within {timeout} seconds."
    )


def delete_and_wait(server, cloud, timeout=60, interval=2) -> None:
    """Delete a server and wait for OpenStack to complete the operation.

    Args:
        server: OpenStack `Server` object (which is an instance of a Mapping).
        cloud: OpenStack Connection object.
        timeout: The maximum number of seconds to wait before exiting.
        interval: Time between requests to OpenStack.

    Raises:
        RuntimeError: Timed out while waiting for the server to be deleted.
    """
    cloud.compute.delete_server(server)
    wait_for_state(
        server,
        target_states={None},
        cloud=cloud,
        timeout=timeout,
        interval=interval,
    )


def create_server(
    name: str,
    config: Mapping,
    group_config: Mapping,
    cloud: Connection,
    block: bool = False,
    user_data: Optional[Path] = Path("userdata.yaml.j2"),
    vars_files: Iterable[Path] = ("secrets.yaml",),
) -> Server:
    """Create and launch an OpenStack server.

    Args:
        name: Instance name.
        config: Mapping containing the (whole) resource definition from
            `resources.yaml`. It is used to read the default values
            (group-independent). Thus, the "deployment" key can optionally be
            stripped.
        group_config: Mapping containing only the configuration for the
            resource group being processed.
        cloud: OpenStack Connection object connected to the cloud where the
            server should be created.
        block: Wait for the server to become active before returning.
        user_data: User data file Jinja template for cloud-init.
        vars_files: Extra variable files to be used when rendering the
            template.
    """
    vars_files = frozenset(vars_files)

    flavor = group_config["flavor"]
    try:
        UUID(hex=flavor)
    except ValueError:  # find flavor by name
        flavor = cloud.compute.find_flavor(flavor)["id"]
    image = config["images"][group_config.get("image", "default")]
    try:
        UUID(hex=image)
    except ValueError:  # find image by name
        image = cloud.compute.find_image(image)["id"]
    key = config["sshkey"]
    network = config["network"]
    try:
        UUID(hex=network)
    except ValueError:  # find network by name
        network = cloud.network.find_network(network)["id"]
    security_groups = config.get("secgroups")
    volume = group_config.get("volume")
    if user_data is not None:
        user_data = template_userdata(
            name,
            config,
            group_config,
            user_data_file=user_data,
            vars_files=vars_files,
        )
    else:
        user_data = ""

    kwargs = {
        "name": name,
        "flavorRef": flavor,
        "imageRef": image,
        "key_name": key,
        "availability_zone": "nova",
        "networks": [{"uuid": network}],
        "user_data": b64encode(user_data.encode("utf-8")).decode("utf-8"),
    }

    if security_groups:
        kwargs["security_groups"] = [
            {"name": security_group} for security_group in security_groups
        ]

    if volume:
        kwargs["block_device_mapping_v2"] = [
            {
                "boot_index": "0" if volume.get("boot", False) else -1,
                "source_type": "blank",
                "destination_type": "volume",
                "volume_size": volume.get("size", 12),
                "volume_type": volume.get("type", "default"),
                "delete_on_termination": True,
            }
        ]

    server = cloud.compute.create_server(**kwargs)

    return (
        wait_for_state(server, {"ACTIVE", "ERROR"}, cloud) if block else server
    )


def synchronize_infrastructure(
    config: dict,
    cloud: Connection,
    user_data: Optional[Path] = Path("userdata.yaml.j2"),
    vars_files: Iterable[Path] = ("secrets.yaml",),
    dry_run: bool = True,
) -> None:
    """Synchronize the VGCN infrastructure.

    Synchronizes the status of the VGCN infrastructure to match the
    configuration provided.

    Args:
        config: Resource definition from `resources.yaml`.
        cloud: OpenStack Connection object connected to the VGCN cloud.
        user_data: User data file Jinja template for newly spawned servers.
        vars_files: Files with variables for templating user data.
        dry_run: Show amount of servers that need to be added or removed from
            each group, but do not apply any changes.
    """
    servers = list(cloud.compute.servers())
    servers_by_group = {
        group: [
            server
            for server in servers
            if server["name"].startswith(f"{PREFIX}{group}")
        ]
        for group in config["deployment"]
    }

    # Compute changes needed to synchronize each group.
    increments: Dict[str, int] = {
        group: compute_increment(
            config["deployment"][group], len(group_servers)
        )
        for group, group_servers in servers_by_group.items()
    }
    removals: Dict[str, List[Server]] = {
        group: servers_by_group[group][0 : abs(increment)]
        for group, increment in increments.items()
    }
    replacements: Dict[str, List[Server]] = {
        group: filter_incorrect_images(
            servers_by_group[group][abs(increment) :],
            config,
            config["deployment"][group],
            cloud,
        )
        for group, increment in increments.items()
    }
    changes: bool = any(
        (
            sum(bool(increment) for increment in increments.values()),
            sum(
                len(list_replacements)
                for list_replacements in replacements.values()
            ),
        )
    )

    # Report planned changes.
    if changes:
        logging.info("Planned changes:")
        for group in servers_by_group:
            increment = increments[group]
            if increment > 0:
                logging.info(f"  - {group}: add {increment} servers")
            elif increment < 0:
                logging.info(f"  - {group}: remove {abs(increment)} servers")
            if replacements[group]:
                logging.info(
                    f"  - {group}: replace image "
                    f"for {len(replacements[group])} servers"
                )

    if dry_run:
        return

    # Add or remove servers.
    server_names = {server["name"] for server in servers}
    for group, increment in increments.items():
        if increment > 0:  # add servers
            for i in range(0, increment):
                name = unique_name(
                    prefix=f"{PREFIX}{group}", existing_names=server_names
                )
                server_names.add(name)
                logging.info(f"Creating server {name}...")
                create_server(
                    name=name,
                    config=config,
                    group_config=config["deployment"][group],
                    cloud=cloud,
                    block=True,
                    user_data=user_data,
                    vars_files=vars_files,
                )
        elif increment < 0:  # remove servers
            for server in removals[group]:
                logging.info(f"Deleting server {server['name']}...")
                remove_server(server, config, cloud)
                server_names.remove(server["name"])

    # Replace images.
    for group, flagged_server in (
        (group, flagged_server)
        for group, flagged_servers in replacements.items()
        for flagged_server in flagged_servers
    ):
        logging.info(f"Replacing image for server {flagged_server['name']}...")
        remove_server(flagged_server, config, cloud)
        create_server(
            name=flagged_server["name"],
            config=config,
            group_config=config["deployment"][group],
            cloud=cloud,
            block=True,
            user_data=user_data,
            vars_files=vars_files,
        )


def make_parser() -> argparse.ArgumentParser:
    """Command line interface for this script."""
    parser = argparse.ArgumentParser(
        prog="synchronize", description="VGCN infrastructure management"
    )

    parser.add_argument(
        "-r",
        "--resources-file",
        dest="resources_file",
        type=str,
        metavar="PATH",
        help="Resources file",
        default="resources.yaml",
    )
    parser.add_argument(
        "-u",
        "--userdata-file",
        dest="userdata_file",
        type=str,
        metavar="PATH",
        help="Userdata file",
        default="userdata.yaml.j2",
    )
    parser.add_argument(
        "-c",
        "--openstack-cloud",
        dest="cloud",
        type=str,
        help="OpenStack cloud name in clouds.yaml",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="dry run mode",
    )

    return parser


if __name__ == "__main__":
    command_parser = make_parser()
    command_args = command_parser.parse_args()

    openstack_cloud = openstack.connect(
        cloud=command_args.cloud,
        load_yaml_config=True,
        load_envvars=False,
    )

    synchronize_infrastructure(
        config=yaml.safe_load(open(command_args.resources_file)),
        user_data=command_args.userdata_file,
        cloud=openstack_cloud,
        dry_run=command_args.dry_run,
    )
