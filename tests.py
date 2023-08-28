"""Tests for the `synchronize` module."""
import concurrent.futures
import datetime
import importlib
import io
import ipaddress
import logging
import sys
import textwrap
import time
from base64 import b64encode
from copy import deepcopy
from multiprocessing import Event as MultiprocessingEvent
from multiprocessing import Pipe, Process, Value
from pathlib import Path
from queue import Queue
from socket import (
    AF_INET,
    SO_REUSEADDR,
    SOCK_STREAM,
    SOL_SOCKET,
    getfqdn,
    socket,
)
from socket import timeout as socket_timeout
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
from typing import List, Mapping, Optional, Type
from uuid import uuid4

import openstack
import pytest
import yaml
from jinja2 import UndefinedError
from openstack.compute.v2.server import Server
from openstack.connection import Connection
from paramiko import (
    Channel,
    ECDSAKey,
    PKey,
    ServerInterface,
    SSHClient,
    Transport,
)
from paramiko.common import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED,
    OPEN_SUCCEEDED,
)
from paramiko.file import BufferedFile
from paramiko.ssh_exception import AuthenticationException

from synchronize import (
    PREFIX,
    SSH_USERNAME,
    RemoteCommandError,
    compute_increment,
    condor_active,
    condor_drain,
    condor_graceful_shutdown,
    condor_off,
    connect_ssh,
    create_server,
    delete_and_wait,
    filter_incorrect_images,
    gracefully_terminate,
    print_stream,
    print_streams,
    remote_command,
    remove_server,
    synchronize_infrastructure,
    template_userdata,
    unique_name,
)

# OpenStack's parameters and parameters for servers spawned during the tests.
AVAILABILITY_ZONE: str = "nova"
CLOUD: str = "vgcn-infrastructure-tests-5987523"
FLAVOR: str = "47d55447-e763-4e8e-9601-b94cfd7be63d"  # m1.tiny
IMAGE: str = "c6906a58-1e05-4be0-8f20-41f24c8320b5"  # Rocky 9.0
IMAGE_NAME: str = "Rocky 9.0"
REPLACEMENT_IMAGE: str = "682994d3-a0f4-4452-831c-9666a717e2ac"  # Rocky 8.5
KEY: str = "kysrpex"
NAME: str = CLOUD
NETWORK: str = "60775850-0c04-4a6d-b607-ad1d75ee2900"  # public
SECGROUP: str = "default"
USERNAME: str = "test"


# Keys for SSH clients and servers used during the tests.
CLIENT_KEY: ECDSAKey = ECDSAKey.generate(bits=384)
HOST_KEY: ECDSAKey = ECDSAKey.generate(bits=384)


def connect() -> Connection:
    """Connect to the OpenStack cloud."""
    return openstack.connect(
        cloud=CLOUD,
        # this name should prevent using an incorrect cloud by accident
        load_yaml_config=True,
        load_envvars=False,
    )


def filter_group(
    server: Mapping,
    group: str,
) -> bool:
    """Filter a server by the group it belongs to.

    Filters a server based on whether its name starts with a given prefix. The
    goal to find out whether the server belongs to a group as it is defined in
    resources.yaml.

    Args:
        server: Mapping with structure analogous to that of OpenStack `Server`
            objects (which are an instances of Mapping).
        group: Computing resources group name.

    Returns:
        `True` when the server's name starts with the provided group name,
        `False` otherwise.
    """
    return server["name"].startswith(f"{PREFIX}{group}")


class BlockingStream(BufferedFile):
    """A file-like wrapper around a pipe.

    Writing to an instance of this object sends the data to the underlying
    pipe. Reading from an instance of this object yields data from the pipe.
    When the end of the pipe is reached the program blocks while waiting for
    new data to come in.

    This class is used to test `print_stream` and `print_streams`.
    """

    def __init__(self) -> None:
        """Initialize the object.

        Configures the `BufferedFile` as readable, writable and opened in
        binary mode, creates the underlying pipe, a "buffer" pipe to
        temporarily store unread bytes, and a lock to prevent simultaneous
        reads.
        """
        self._terminate = False
        self._flags = 0
        super().__init__()
        self._bufsize = 1
        self._flags |= BufferedFile.FLAG_READ
        self._flags |= BufferedFile.FLAG_WRITE
        self._flags |= BufferedFile.FLAG_BINARY
        self._read_pipe, self._write_pipe = Pipe(duplex=False)
        self._read_buffer, self._write_buffer = Pipe(duplex=False)
        self._read_lock = Lock()

    def _read(self, size: int) -> Optional[bytes]:
        """Read from the underlying pipe.

        Args:
            size: Amount of bytes to read.
        """
        self._read_lock.acquire()

        # previously read data (if any)
        data = (
            self._read_buffer.recv_bytes() if self._read_buffer.poll() else b""
        )
        if len(data) < size and not self._terminate:
            # read from the pipe
            data += self._read_pipe.recv_bytes()
        # save unused data for later
        self._write_buffer.send_bytes(data[size:])

        if self._terminate:
            # return EOF when `close` is called
            return None

        self._read_lock.release()

        return data[0:size]

    def _write(self, data: bytes) -> int:
        """Write to the underlying pipe.

        Args:
            data: Amount of bytes to write to the pipe.

        Returns:
            Amount of bytes written to the pipe.
        """
        self._write_pipe.send_bytes(data)
        return len(data)

    def close(self) -> None:
        """Close the file-like object."""
        super().close()
        self._terminate = True
        # write something to the pipe to unblock a potential in-progress pipe
        # read
        self._write_pipe.send_bytes(b"\n")


class SSHServer(ServerInterface):
    """Basic SSH server implementation for tests.

    This class uses `ServerInterface` to implement an SSH server that
    can be contacted to run two predefined commands that produce specific
    outputs.

    This class is used to test, for example, `connect_ssh` and
    `remote_command`. It is also inherited by another class `CondorServer`,
    that further tests depend on.
    """

    client_key: Optional[PKey] = None

    def __init__(self, client_key: Optional[PKey] = None):
        """Initialize the SSH server."""
        super().__init__()
        self.client_key = client_key

    def check_channel_request(self, kind: str, chanid: int) -> int:
        """Allow channel requests of kind `session`."""
        if kind == "session":
            return OPEN_SUCCEEDED

        return OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_publickey(self, username: str, key: PKey) -> int:
        """Allow only clients created for the test to authenticate."""
        if key == (self.client_key or CLIENT_KEY) and username == SSH_USERNAME:
            return AUTH_SUCCESSFUL

        return AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        """Allow only public key authentication."""
        return "publickey"

    def check_channel_shell_request(self, channel) -> bool:
        """Allow shell requests (dummy)."""
        return True

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ) -> bool:
        """Allow pseudo terminal requests (dummy)."""
        return True

    def check_channel_exec_request(
        self, channel: Channel, command: bytes
    ) -> bool:
        """Handle command execution requests.

        Two predefined commands can be executed: "command" and "fail". The
        former returns a zero exit code, while the latter returns a nonzero
        exit code.
        """
        if command == b"command":
            stdout = b"text"
            stderr = b"error"
            channel.send(stdout)
            channel.send_stderr(stderr)
            channel.send_exit_status(0)
            channel.shutdown_write()
            return True
        elif command == b"fail":
            stdout = b"fail_text"
            stderr = b"fail_error"
            channel.send(stdout)
            channel.send_stderr(stderr)
            channel.send_exit_status(1)
            channel.shutdown_write()
            return True

        channel.send_exit_status(1)
        channel.shutdown_write()
        return False


class CondorServer(SSHServer):
    """SSH server for testing condor commands.

    This class mocks a server running condor, so that `condor_drain`,
    `condor_active`, `condor_off` and `condor_graceful_shutdown` can be tested.
    """

    hostname: str = "condor_worker"
    ip: str = "198.51.100.1"  # Prefix for examples (RFC5737)
    drained: bool = False

    def check_channel_exec_request(
        self, channel: Channel, command: bytes
    ) -> bool:
        """Handle command execution requests."""
        command = command.replace(
            b"`hostname -f`",
            self.hostname.encode("utf-8"),
        )
        command = command.split()

        mapping = {
            b"condor_drain": self._handle_condor_drain,
            b"condor_status": self._handle_condor_status,
            b"condor_off": self._handle_condor_off,
        }
        for name, handler in mapping.items():
            if command[0].endswith(name):
                return handler(channel, command)

        return False

    def _handle_condor_drain(
        self, channel: Channel, command: List[bytes]
    ) -> bool:
        """Mocks the `condor_drain` command.

        Only one (positional) argument is accepted, and it is supposed to be
        the hostname of the machine to drain.
        """
        if len(command) > 2:
            channel.send_stderr(
                b"This is a mock server that pretends to run condor. "
                b"It only accepts one positional argument for"
                b"`condor_drain` (the machine to drain).\n"
            )
            channel.send_exit_status(1)
            channel.shutdown_write()
            return True

        # check whether an ip-address or a hostname has been provided
        try:
            ip_address = ipaddress.ip_address(command[1].decode("utf-8"))
        except ValueError:
            ip_address = None

        if any(
            (
                self.hostname.encode("utf-8") == command[1],
                self.ip.encode("utf-8") == command[1],
            )
        ):
            # when the correct ip address or hostname has been provided,
            # react to the drain command
            if self.drained:
                channel.send_stderr(b"ERROR: Draining already in progress")
                channel.send_exit_status(1)
            else:
                self.drained = True
                channel.send(
                    b"Sent request to drain " + self.hostname.encode("utf-8")
                )
                channel.send_exit_status(0)
        elif ip_address:
            # invalid IP address
            channel.send_stderr(
                b"ERROR: Can't find address for startd " + command[1]
            )
            channel.send_exit_status(1)
        else:
            # invalid hostname
            channel.send_stderr(b"ERROR: unknown host " + command[1])
            channel.send_exit_status(1)

        channel.shutdown_write()
        return True

    def _handle_condor_status(
        self, channel: Channel, command: List[bytes]
    ) -> bool:
        """Mocks the `condor_status` command.

        A command of the form `condor_status | grep slot.*@hostname is
        expected.
        """
        try:
            grep = command[3]
            grep = not any(
                (
                    not grep.split(b"@")[0].startswith(b"slot"),
                    not grep.split(b"@")[1]
                    in {
                        self.hostname.encode(),
                        self.ip.encode(),
                    },
                )
            )
        except IndexError:
            grep = False
        invalid = any(
            (
                len(command) != 4,
                command[1] != b"|",
                command[2] != b"grep",
                not grep,
            )
        )
        if invalid:
            channel.send_stderr(
                b"This is a mock server that pretends to run condor. "
                b"It only accepts the following condor_status command:"
                b"`condor_status | grep slot.*@`hostname -f``\n"
            )
            channel.send_stderr(str(grep).encode())
            channel.send_exit_status(1)
            channel.shutdown_write()
            return True

        host = command[3].split(b"@")[1]
        try:
            ip_address = ipaddress.ip_address(host.decode("utf-8"))
        except ValueError:
            ip_address = None
        if (not ip_address and host == self.hostname.encode("utf-8")) or (
            ip_address and host == self.ip.encode("utf-8")
        ):
            status = (
                (
                    f"slot1@{self.hostname if not ip_address else self.ip}    "
                    f"LINUX      X86_64 Unclaimed Idle      "
                    f"0.000   33013 56+21:52:13\n"
                    f"slot1_1@{self.hostname if not ip_address else self.ip}  "
                    f"LINUX      X86_64 Claimed   Idle      "
                    f"0.000    4096 13+22:07:56\n"
                    f"slot1_2@{self.hostname if not ip_address else self.ip}  "
                    f"LINUX      X86_64 Claimed   Idle      "
                    f"0.000    4096  3+17:32:58\n"
                )
                if not self.drained
                else ""
            )
        else:
            status = ""
        channel.send(status.encode("utf-8"))
        channel.send_exit_status(0 if status else 1)

        channel.shutdown_write()
        return True

    def _handle_condor_off(
        self,
        channel: Channel,
        command: List[bytes],
    ):
        """Mocks the `condor_off` command.

        Any arguments are accepted, as they will be ignored.
        """
        channel.send_exit_status(0)
        channel.shutdown_write()
        return True


def launch_ssh_server(
    port_number: Value,
    event_port: MultiprocessingEvent,
    event_termination: MultiprocessingEvent,
    server_class: str = f"{__name__}.{SSHServer.__qualname__}",
) -> None:
    """Launches an SSH server implemented as a Python class.

    Launches an SSH server and waits for a client to connect and run commands.

    Args:
        port_number: This function is meant to run as a subprocess.
            `port_number` is a variable shared with the parent process where
            the function is meant to write the port number that has been chosen
            for the server (it will be selected randomly). The parent process
            can later read from this variable to connect to the selected port.
        event_port: An event used to signal that a port has already been
            selected and written to the shared variable `port_number`.
        event_termination: An event used by the parent process to signal that
            the server spawned by this function is no longer needed and can be
            shutdown.
        server_class: Python class implementing the SSH server.
    """
    module, class_ = server_class.split(".")
    server_class = getattr(importlib.import_module(module), class_)

    # Create a socket.
    server_socket = socket(AF_INET, SOCK_STREAM)
    server_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))  # randomly selected port number

    # Share the selected port number with the parent process.
    port_number.value = server_socket.getsockname()[1]
    event_port.set()

    # Wait for an incoming connection from an SSH client.
    server_socket.listen(3600)
    client, address = server_socket.accept()

    # Use the connection to set up a transport.
    transport = Transport(client)
    transport.set_gss_host(getfqdn(""))
    transport.load_server_moduli()
    transport.add_server_key(HOST_KEY)

    # Start a server over the transport.
    server = server_class()
    transport.start_server(server=server)

    # Wait for the client to authenticate.
    channel = transport.accept(timeout=3600)

    # Wait for the parent process to signal that the SSH server is no longer
    # needed.
    event_termination.wait(timeout=3600)

    # Close the channel and the transport.
    channel.close()
    transport.close()


@pytest.fixture()
def ssh_server():
    """Fixture returning a function that spawns an SSH server subprocess."""

    def function(class_: Type) -> (Process, int, MultiprocessingEvent):
        """Spawn an SSH server in a subprocess."""
        port = Value("I", 0)
        event_port = MultiprocessingEvent()
        event_termination = MultiprocessingEvent()
        server = Process(
            target=launch_ssh_server,
            args=(
                port,
                event_port,
                event_termination,
                f"{__name__}.{class_.__qualname__}",
            ),
        )
        server.start()
        event_port.wait()
        port = port.value
        return server, port, event_termination

    return function


@pytest.fixture()
def ssh_client():
    """Fixture returning a function that spawns and connects an SSH client."""

    def function(port: int) -> SSHClient:
        """Spawn an SSH client and connect it to localhost."""
        client = SSHClient()
        client.get_host_keys().add(
            hostname=f"[127.0.0.1]:{port}",
            keytype="ecdsa-sha2-nistp384",
            key=HOST_KEY,
        )
        client.connect(
            "127.0.0.1",
            username=SSH_USERNAME,
            port=port,
            pkey=CLIENT_KEY,
            allow_agent=False,
            look_for_keys=False,
        )
        return client

    return function


@pytest.fixture()
def openstack_server():
    """Fixture returning an OpenStack server."""

    def function(cloud: Optional[Connection]) -> Server:
        """Create an OpenStack server."""
        cloud = cloud or connect()

        # Add host and client keys to userdata.
        private_key = io.StringIO()
        HOST_KEY.write_private_key(private_key)
        private_key.seek(0)
        private_key = private_key.read()
        private_key = private_key.replace("\n", "\\n")
        user_data = textwrap.dedent(
            f"""
            #cloud-config
            # package_update: false
            # package_upgrade: false
            users:
              - name: {USERNAME}
                gecos: {USERNAME}
                sudo: ALL=(ALL) NOPASSWD:ALL
                groups: users, admin
                ssh_authorized_keys:
                  - ecdsa-sha2-nistp384 {CLIENT_KEY.get_base64()}
            ssh_keys:
              ecdsa_public: ecdsa {HOST_KEY.get_base64()}
              ecdsa_private: "{private_key}"
        """
        )[1:]

        return cloud.compute.create_server(
            name=NAME,
            flavorRef=FLAVOR,
            imageRef=IMAGE,
            key_name=KEY,
            availability_zone=AVAILABILITY_ZONE,
            networks=[{"uuid": NETWORK}],
            user_data=b64encode(user_data.encode("utf-8")).decode("utf-8"),
        )

    return function


@pytest.fixture()
def openstack_condor_set_up():
    """Fixture that sets up an OpenStack server to mock Condor."""
    timeout_server_active: int = 30
    timeout_ssh_online: int = 30
    timeout_ssh_connect: int = 10

    def function(
        server: Server,
        cloud: Connection,
    ) -> None:
        server = cloud.compute.wait_for_server(
            server,
            status="ACTIVE",
            interval=1,
            wait=timeout_server_active,
        )

        client = SSHClient()
        ips = {
            address["addr"]
            for network, addresses in server["addresses"].items()
            for address in addresses
        }
        for ip in ips:
            client.get_host_keys().add(
                hostname=f"{ip}", keytype="ecdsa-sha2-nistp384", key=HOST_KEY
            )

        start = time.time()
        while time.time() - start < timeout_ssh_online:
            try:
                ip = connect_ssh(
                    client,
                    server,
                    port=22,
                    username=USERNAME,
                    pkey=CLIENT_KEY,
                )
            except RuntimeError:
                time.sleep(1)
                continue
            break
        else:
            raise RuntimeError("Timed out waiting for SSH service.")

        client.connect(
            ip,
            username=USERNAME,
            port=22,
            timeout=timeout_ssh_connect,
            pkey=CLIENT_KEY,
            allow_agent=False,
            look_for_keys=False,
        )

        folder = Path(__file__).parent
        synchronize = (folder / "synchronize.py").absolute()
        tests = (folder / "tests.py").absolute()
        requirements = (folder / "requirements.txt").absolute()

        private_key = io.StringIO()
        CLIENT_KEY.write_private_key(private_key)
        private_key.seek(0)

        sftp_client = client.open_sftp()
        sftp_client.put(str(synchronize), f"/home/test/{synchronize.name}")
        sftp_client.put(str(tests), f"/home/test/{tests.name}")
        sftp_client.put(str(requirements), f"/home/test/{requirements.name}")
        sftp_client.putfo(
            io.BytesIO(private_key.read().encode("utf-8")),
            "/home/test/client_key",
        )
        python_script = textwrap.dedent(
            """
            #!/usr/bin/env python
            from socket import (
                AF_INET,
                SO_REUSEADDR,
                SOCK_STREAM,
                SOL_SOCKET,
                getfqdn,
                socket,
            )
            from time import sleep

            from paramiko import ECDSAKey, Transport

            from tests import CondorServer

            CLIENT_KEY = ECDSAKey.from_private_key_file(
                "/home/test/client_key"
            )
            HOST_KEY = ECDSAKey.from_private_key_file(
                "/etc/ssh/ssh_host_ecdsa_key"
            )

            server_socket = socket(AF_INET, SOCK_STREAM)
            server_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            server_socket.bind(("0.0.0.0", 22))
            server_socket.listen(60)
            file = open("/home/test/server_is_up", "w")
            file.close()
            client, address = server_socket.accept()

            transport = Transport(client)
            transport.set_gss_host(getfqdn(""))
            transport.load_server_moduli()
            transport.add_server_key(HOST_KEY)

            server = CondorServer(client_key=CLIENT_KEY)
            transport.start_server(server=server)
            channel = transport.accept(timeout=60)

            sleep(60)

            channel.close()
            transport.close()
        """
        )[1:]
        sftp_client.putfo(
            io.BytesIO(python_script.encode("utf-8")),
            "/home/test/condor_server.py",
        )
        sftp_client.close()

        try:
            remote_command("sudo dnf install -y python3-pip", client, log=True)
            remote_command(
                "sudo pip3 install -r /home/test/requirements.txt",
                client,
                log=True,
            )
            remote_command(
                "chmod +x /home/test/condor_server.py", client, log=True
            )
            remote_command("sudo systemctl stop sshd", client, log=True)
            client.exec_command("nohup sudo /home/test/condor_server.py &")
            remote_command(
                "WAIT=0; "
                "until [ -f /home/test/server_is_up ] || [ $WAIT -eq 30 ]; "
                "do sleep $(( WAIT++ )); done",
                client,
                log=True,
            )
        except RemoteCommandError as exception:
            logging.error(exception.stdout.decode("utf-8"))
            logging.error(exception.stderr.decode("utf-8"))
            raise exception

        client.close()

    return function


def test_print_stream() -> None:
    """Tests the `print_stream` function.

    The test consists of spawning a "program" in the form of a thread that will
    write to a BlockingStream object. The function `print_stream` is then
    be called on the BlockingStream object.

    After that, the contents of the printed stream are checked for correctness
    at different points in time.
    """

    def program(
        program_stdout: BlockingStream,
        program_lock: Lock,
    ) -> None:
        """Function simulating a running process (runs in a thread).

        Args:
            program_stdout: Stream simulating the program's stdout.
            program_lock: Lock for controlling the program from outside.
        """
        print("text1", file=program_stdout)
        program_lock.acquire()
        print("text2", file=program_stdout)

    # Allocate objects to handle stream contents.
    stdout = BlockingStream()  # the "program" writes here its stdout
    queue_stdout = Queue()  # `print_stream` writes here

    # Start the "program".
    lock = Lock()
    lock.acquire()
    thread = Thread(target=program, args=(stdout, lock))
    thread.start()

    # Write the output in real time to a queue object (line-by-line).
    printer = Thread(
        target=print_stream,
        args=(stdout, lambda line: queue_stdout.put(line + b"\n"), False),
    )
    printer.start()

    # Wait for the program to write to stdout and for the printer thread to
    # put the output in the queue. After everything is done, the queue should
    # contain "text1".
    bytes_stdout = bytes()
    bytes_stdout += queue_stdout.get(block=True)
    assert bytes_stdout == b"text1\n"
    # resume execution of the program
    lock.release()

    # Wait again for the program to write to stdout. It should now have
    # finished and thus written "text2" to stdout.
    bytes_stdout = bytes()
    bytes_stdout += queue_stdout.get(block=True)
    assert bytes_stdout == b"text2\n"

    # The printer thread is still running and waiting for input, so we close
    # the BlockingStream object to terminate it (that will make the printer
    # thread receive an EOF signal).
    stdout.close()

    # Test saving the output.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        # Allocate objects to handle stream contents.
        stdout = BlockingStream()
        queue_stdout = Queue()

        # Start the "program".
        lock = Lock()
        thread = Thread(target=program, args=(stdout, lock))
        thread.start()

        # Write the output to the queue object.
        future = executor.submit(
            print_stream,
            stdout,
            print_function=lambda line: queue_stdout.put(line + b"\n"),
            save=True,
        )

        # Wait for the contents to be processed by print_stream and then close
        # the BlockingStream object.
        for i in range(0, 2):  # (two lines expected)
            queue_stdout.get(block=True)
        stdout.close()

        output = future.result()

        assert output == b"text1\ntext2\n"


def test_print_streams() -> None:
    """Tests the `print_streams` function.

    The tests consist of spawning a "program" in the form of a thread that will
    write to BlockingStream objects. The function `print_streams` is then
    called on the BlockingStream objects.

    After that, the contents of the streams are checked for correctness at
    different points in time.
    """

    def program(
        program_stdout: BlockingStream,
        program_stderr: BlockingStream,
        program_lock: Lock,
    ) -> None:
        """Function simulating a running process (runs in a thread).

        Args:
            program_stdout: Stream simulating the program's stdout.
            program_stderr: Stream simulating the program's stderr.
            program_lock: Lock for controlling the program from outside.
        """
        print("text1", file=program_stdout)
        print("error1", file=program_stderr)
        program_lock.acquire()
        print("text2", file=program_stdout)
        print("error2", file=program_stderr)
        program_lock.acquire()
        print("text3", file=program_stdout)
        print("error3", file=program_stderr)

    # Allocate objects to handle stream contents.
    stdout = BlockingStream()  # the "program" writes here its stdout
    stderr = BlockingStream()  # the "program" writes here its stderr
    queue_stdout = Queue()  # `print_streams` writes here
    queue_stderr = Queue()  # `print_streams` writes here

    # Start the "program".
    lock = Lock()
    lock.acquire()
    thread = Thread(target=program, args=(stdout, stderr, lock))
    thread.start()

    # Write the output in real time to queue objects (line-by-line).
    printer = Thread(
        target=print_streams,
        args=(
            (stdout, stderr),
            (
                lambda line: queue_stdout.put(line + b"\n"),
                lambda line: queue_stderr.put(line + b"\n"),
            ),
            (False, False),
        ),
    )
    printer.start()

    # Wait for the program to write to stdout and for the printer thread to
    # put the output in the queues. After everything is done, the stdout queue
    # should contain "text1" and the stderr queue should be empty.
    bytes_stdout = bytes()
    bytes_stdout += queue_stdout.get(block=True)
    assert bytes_stdout == b"text1\n"
    bytes_stderr = bytes()
    bytes_stderr += queue_stderr.get(block=True)
    assert bytes_stderr == b"error1\n"
    # resume execution of the program
    lock.release()

    # Wait now for the program to write to stderr. It should be blocked waiting
    # for the lock to be released and its stderr should contain "error".
    bytes_stdout = bytes()
    bytes_stdout += queue_stdout.get(block=True)
    assert bytes_stdout == b"text2\n"
    bytes_stderr = bytes()
    bytes_stderr += queue_stderr.get(block=True)
    assert bytes_stderr == b"error2\n"
    # resume execution of the program
    lock.release()

    # Now the program should have finished and written "text2" to stdout.
    bytes_stdout = bytes()
    bytes_stdout += queue_stdout.get(block=True)
    assert bytes_stdout == b"text3\n"
    bytes_stderr = bytes()
    bytes_stderr += queue_stderr.get(block=True)
    assert bytes_stderr == b"error3\n"

    # The printer thread is still running and waiting for input, so we close
    # the BlockingStream objects to terminate it (that will make the printer
    # thread receive EOF signals).
    stdout.close()
    stderr.close()

    # Test saving the output.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        # Allocate objects to handle stream contents.
        stdout = BlockingStream()
        stderr = BlockingStream()
        queue_stdout = Queue()
        queue_stderr = Queue()

        # Start the "program".
        lock = Lock()
        lock.acquire()
        thread = Thread(target=program, args=(stdout, stderr, lock))
        thread.start()

        # Write the output to the queue object.
        future = executor.submit(
            print_streams,
            (stdout, stderr),
            print_functions=(
                lambda line: queue_stdout.put(line),
                lambda line: queue_stderr.put(line),
            ),
            save=(True, True),
        )

        # Wait for the contents to be processed by print_stream and then close
        # the BlockingStream object.
        for i in range(0, 3):  # (three lines expected)
            queue_stdout.get(block=True)
            queue_stderr.get(block=True)
            lock.release()
        stdout.close()
        stderr.close()

        stdout, stderr = future.result()

        assert stdout == b"text1\ntext2\ntext3\n"
        assert stderr == b"error1\nerror2\nerror3\n"


def test_remote_command(caplog, ssh_server, ssh_client) -> None:
    """Tests the `remote_command` function.

    Launches an SSH server (implemented as the `ParamikoServer` class) and
    executes predefined commands that the server accepts.
    """
    caplog.set_level("DEBUG")

    # Test `log=False`
    server, port, event_termination = ssh_server(SSHServer)
    client = ssh_client(port)

    stdout, stderr = remote_command("command", client, False)
    assert b"text" == stdout
    assert b"error" == stderr
    log_records = tuple(
        record for record in caplog.records if record.module == "synchronize"
    )
    assert len(log_records) == 0

    with pytest.raises(RemoteCommandError) as exception_info:
        remote_command("fail", client, False)
        assert b"fail_text" == exception_info.value.stdout
        assert b"fail_error" == exception_info.value.stderr

    event_termination.set()
    server.terminate()

    # Test `log=True`
    server, port, event_termination = ssh_server(SSHServer)
    client = ssh_client(port)

    stdout, stderr = remote_command("command", client, True)
    assert b"text" == stdout
    assert b"error" == stderr
    log_records = tuple(
        record for record in caplog.records if record.module == "synchronize"
    )
    assert len(log_records) == 3
    assert log_records[0].message == "Remote SSH command: command"
    assert log_records[0].levelname == "INFO"
    assert log_records[1].message == "text"
    assert log_records[1].levelname == "DEBUG"
    assert log_records[2].message == "error"
    assert log_records[2].levelname == "DEBUG"

    event_termination.set()
    server.terminate()


def test_unique_name() -> None:
    """Test `unique_name`."""
    prefix = "vgcn-infrastructure-test-?18$98976👾"
    existing_names = {f"{prefix}-0" f"{prefix}-0000" f"{prefix}-0001"}

    name = unique_name(prefix)
    assert type(name) == str
    assert name.startswith(f"{prefix}-")
    suffix = int(name[len(f"{prefix}-") :])
    assert 0 <= suffix <= 9999
    assert name not in existing_names


def test_connect_ssh(caplog, ssh_server, ssh_client) -> None:
    """Test `connect_ssh`."""
    # Running `connect_ssh` on `server1` will always fail, because
    # all the IP addresses belong to unusable network prefixes.
    server1 = {
        "name": "server-4492",
        "addresses": {
            "network1": [
                {
                    "version": 4,
                    "addr": "198.51.100.1",  # Prefix for examples (RFC5737)
                    "OS-EXT-IPS:type": "fixed",
                    "OS-EXT-IPS-MAC:mac_addr": "fd:5a:b9:7a:cf:5f",  # random
                },
                {
                    "version": 6,
                    # random
                    "addr": "100::beef",  # IPv6 black hole (RFC6666)
                    "OS-EXT-IPS:type": "fixed",
                    "OS-EXT-IPS-MAC:mac_addr": "fd:5a:b9:7a:cf:5f",
                },
            ],
            "network2": [
                {
                    "version": 4,
                    "addr": "198.51.100.56",  # Prefix for examples (RFC5737)
                    "OS-EXT-IPS:type": "fixed",
                    "OS-EXT-IPS-MAC:mac_addr": "fd:5b:b9:7a:cf:5f",
                }
            ],
        },
    }

    # `server2` includes the loopback address (so the test for this one can
    # succeed).
    server2 = {
        "name": "server-9376",
        "addresses": {
            "network3": [
                {
                    "version": 4,
                    "addr": "127.0.0.1",
                    "OS-EXT-IPS:type": "fixed",
                    "OS-EXT-IPS-MAC:mac_addr": "fd:5c:b9:7a:cf:5f",  # random
                },
            ]
        },
    }

    # Prepare an SSH client for the tests.
    client = SSHClient()

    # Test server1
    # ------------
    # The connection is expected to fail due to the hosts being unreachable
    # (socket errors).
    # - verify that the correct exception is raised
    with pytest.raises(RuntimeError) as exception_info:
        connect_ssh(
            client,
            server1,
            timeout=5,
        )
        assert "Unable to gain ssh access to" in str(exception_info.value)
        assert server1["name"] in str(exception_info.value)
    # - verify that the expected log messages are written
    log_records = tuple(
        record
        for record in caplog.records
        if all(
            (
                record.module == "synchronize",
                record.funcName == "connect_ssh",
            )
        )
    )
    assert len(log_records) == 3
    assert all(
        any(
            (
                all(
                    (
                        issubclass(record.exc_info[0], OSError),
                        # [0] -> exception type
                        record.exc_info[1].errno
                        == 101,  # [1] -> exception object
                    )
                ),
                issubclass(record.exc_info[0], socket_timeout),
            )
        )
        for record in log_records
    )

    # Test server2 (A)
    # The connection is expected to fail due to an authentication error.
    # ----------------
    server, port, event_termination = ssh_server(SSHServer)
    # - add the server's host key to the client
    client.get_host_keys().add(
        hostname=f"[127.0.0.1]:{port}",
        keytype="ecdsa-sha2-nistp384",
        key=HOST_KEY,
    )
    # - run a test that will fail because the wrong username is provided
    with pytest.raises(RuntimeError) as exception_info:
        connect_ssh(
            client,
            server2,
            port=port,
            username="invalidate" + SSH_USERNAME,
            pkey=CLIENT_KEY,
            timeout=5,
        )
        assert "Unable to gain ssh access to" in str(exception_info.value)
        assert server2["name"] in str(exception_info.value)
    log_records = tuple(
        record
        for record in caplog.records[3:]
        if all(
            (
                record.module == "synchronize",
                record.funcName == "connect_ssh",
            )
        )
    )
    assert len(log_records) == 1
    assert all(
        issubclass(record.exc_info[0], AuthenticationException)
        for record in log_records
    )
    event_termination.set()

    # Test server2 (B)
    # The test should succeed.
    # ----------------
    server, port, event_termination = ssh_server(SSHServer)
    # - add the server's host key to the client
    client.get_host_keys().add(
        hostname=f"[127.0.0.1]:{port}",
        keytype="ecdsa-sha2-nistp384",
        key=HOST_KEY,
    )
    # - attempt to connect
    ip = connect_ssh(
        client,
        server2,
        port=port,
        username=SSH_USERNAME,
        pkey=CLIENT_KEY,
        timeout=5,
    )
    event_termination.set()
    assert ip == "127.0.0.1"


def test_condor_drain(ssh_server, ssh_client) -> None:
    """Test `condor_drain`."""
    server, port, event_termination = ssh_server(CondorServer)
    client = ssh_client(port)

    condor_drain(client)

    event_termination.set()
    server.terminate()


def test_condor_active(ssh_server, ssh_client) -> None:
    """Test `condor_active`."""
    server, port, event_termination = ssh_server(CondorServer)
    client = ssh_client(port)

    assert condor_active(client)

    condor_drain(client)
    assert not condor_active(client)

    event_termination.set()
    server.terminate()


def test_condor_off(ssh_server, ssh_client) -> None:
    """Test `condor_off`."""
    server, port, event_termination = ssh_server(CondorServer)
    client = ssh_client(port)

    condor_off(client)

    event_termination.set()
    server.terminate()


def test_condor_graceful_shutdown(ssh_client, ssh_server) -> None:
    """Test `condor_graceful_shutdown`."""
    server, port, event_termination = ssh_server(CondorServer)
    client = ssh_client(port)

    condor_graceful_shutdown(client)

    event_termination.set()
    server.terminate()


def test_gracefully_terminate(
    openstack_server, openstack_condor_set_up
) -> None:
    """Test `gracefully_terminate`."""
    cloud = connect()

    server = openstack_server(cloud)
    try:
        openstack_condor_set_up(server, cloud)

        gracefully_terminate(server, cloud, timeout=30, pkey=CLIENT_KEY)
    finally:
        delete_and_wait(server, cloud)


def test_compute_increment() -> None:
    """Test `compute_increment`."""
    status = 4

    group_config = {"count": 4}
    assert compute_increment(group_config, status) == 0

    group_config = {"count": 2}
    assert compute_increment(group_config, status) == -2

    group_config = {"count": 6}
    assert compute_increment(group_config, status) == 2

    group_config = {
        "count": 4,
        "start": datetime.date.today(),
        "end": datetime.date.today(),
    }
    assert compute_increment(group_config, status) == 0

    group_config = {
        "count": 8,
        "start": datetime.date.today(),
        "end": datetime.date.today(),
    }
    assert compute_increment(group_config, status) == 4

    group_config = {
        "count": 4,
        "start": datetime.date.today() - datetime.timedelta(days=2),
        "end": datetime.date.today() - datetime.timedelta(days=1),
    }
    assert compute_increment(group_config, status) == -4

    group_config = {
        "count": 4,
        "start": datetime.date.today() + datetime.timedelta(days=1),
        "end": datetime.date.today() + datetime.timedelta(days=2),
    }
    assert compute_increment(group_config, status) == -4


def test_filter_incorrect_images() -> None:
    """Test `filter_incorrect_images`."""
    cloud = connect()

    config_string = textwrap.dedent(
        f"""
        ---
        images:
            default: {IMAGE}
        network: {NETWORK}
        secgroups:
            - {SECGROUP}
        sshkey: {KEY}
        pubkeys:
          - "{ECDSAKey.generate(bits=384).get_base64()}"

        graceful: false

        deployment:
          worker-{NAME}:
            count: 3
            flavor: {uuid4()}
    """
    )[1:]
    config = yaml.safe_load(config_string)
    group = next(iter(config["deployment"]))
    group_config = config["deployment"][group]

    servers = [
        {
            "id": str(uuid4()),
            "image": {"id": IMAGE},
        },
        {
            "id": str(uuid4()),
            "image": {"id": REPLACEMENT_IMAGE},
        },
    ]

    # Test image UUID.
    assert filter_incorrect_images(servers, config, group_config, cloud) == [
        servers[1]
    ]

    # Test image name.
    modified_config = deepcopy(config)
    modified_config["images"]["default"] = IMAGE_NAME
    assert filter_incorrect_images(
        servers, modified_config, group_config, cloud
    ) == [servers[1]]

    # Test invalid image name.
    modified_config = deepcopy(config)
    modified_config["images"]["default"] = NAME + "invalid_image_name"
    with pytest.raises(TypeError):
        filter_incorrect_images(servers, modified_config, group_config, cloud)

    # Test server using volume (no image).
    servers += [
        {
            "id": str(uuid4()),
            "image": {"id": None},
        },
    ]
    assert filter_incorrect_images(servers, config, group_config, cloud) == [
        servers[1]
    ]


def test_remove_server(openstack_server, openstack_condor_set_up) -> None:
    """Test `remove_server`."""
    cloud = connect()

    server = openstack_server(cloud)
    try:
        openstack_condor_set_up(server, cloud)

        config = {"graceful": True}
        remove_server(server, config, cloud, pkey=CLIENT_KEY)
    finally:
        delete_and_wait(server, cloud)

    server = openstack_server(cloud)
    try:
        openstack_condor_set_up(server, cloud)

        config = {"graceful": False}
        remove_server(server, config, cloud)
    finally:
        delete_and_wait(server, cloud)


def test_template_userdata() -> None:
    """Test `template_userdata`."""
    config_string = textwrap.dedent(
        f"""
        ---
        images:
            default: {uuid4()}
        network: default
        secgroups:
            - secgroup
        sshkey: key
        pubkeys:
          - "{ECDSAKey.generate(bits=384).get_base64()}"

        graceful: true

        deployment:
          worker-{NAME}:
            count: 3
            flavor: {uuid4()}
    """
    )[1:]

    user_data = textwrap.dedent(
        """
        #cloud-config
        write_files:
          - content: |
              Count = {{ count }}
              Password = {{ password }}
            owner: root:root
            path: /etc/configuration_file
            permissions: "0644"
            docker: {{ docker }}
    """
    )[1:]

    variables = textwrap.dedent(
        """
        ---
        password: 1234567890
    """
    )[1:]

    config = yaml.safe_load(config_string)
    group = next(iter(config["deployment"]))
    group_config = config["deployment"][group]

    # Successful rendering.
    with NamedTemporaryFile("w") as user_data_file, NamedTemporaryFile(
        "w"
    ) as vars_file:
        user_data_file.write(user_data)
        user_data_file.flush()

        vars_file.write(variables)
        vars_file.flush()

        templated = template_userdata(
            unique_name(group, set()),
            config,
            group_config,
            Path(user_data_file.name),
            (Path(vars_file.name),),
        )
    expected = textwrap.dedent(
        """
        #cloud-config
        write_files:
          - content: |
              Count = 3
              Password = 1234567890
            owner: root:root
            path: /etc/configuration_file
            permissions: "0644"
            docker: False
    """
    )[1:-1]
    assert templated == expected

    # Missing variables: exception expected.
    with NamedTemporaryFile("w") as user_data_file, pytest.raises(
        UndefinedError
    ):
        user_data_file.write(user_data)
        user_data_file.flush()

        template_userdata(
            unique_name(group, set()),
            config,
            group_config,
            Path(user_data_file.name),
        )


def test_delete_and_wait(openstack_server) -> None:
    """Test `delete_and_wait`."""
    cloud = connect()

    server = openstack_server(cloud=cloud)
    try:
        assert cloud.compute.find_server(server["id"]) is not None
        assert cloud.compute.find_server(server["id"])["id"] == server["id"]
        delete_and_wait(server, cloud)
        assert cloud.compute.find_server(server["id"]) is None
    finally:
        cloud.compute.delete_server(server)


def test_create_server() -> None:
    """Test `create_server`."""
    cloud = connect()

    config_string = textwrap.dedent(
        f"""
        ---
        images:
            default: {IMAGE}
        network: {NETWORK}
        secgroups:
            - {SECGROUP}
        sshkey: {KEY}
        pubkeys:
          - "{ECDSAKey.generate(bits=384).get_base64()}"

        graceful: false

        deployment:
          worker-{NAME}:
            count: 3
            flavor: {FLAVOR}
        """
    )[1:]

    user_data = textwrap.dedent(
        """
        #cloud-config
        write_files:
          - content: |
              Count = {{ count }}
              Password = {{ password }}
            owner: root:root
            path: /etc/configuration_file
            permissions: "0644"
    """
    )[1:]

    variables = textwrap.dedent(
        """
        ---
        password: 1234567890
    """
    )[1:]

    config = yaml.safe_load(config_string)
    group = next(iter(config["deployment"]))
    group_config = config["deployment"][group]

    with NamedTemporaryFile("w") as user_data_file, NamedTemporaryFile(
        "w"
    ) as vars_file:
        user_data_file.write(user_data)
        user_data_file.flush()

        vars_file.write(variables)
        vars_file.flush()

        server = create_server(
            name=unique_name(group, set()),
            config=config,
            group_config=group_config,
            cloud=cloud,
            block=True,
            user_data=Path(user_data_file.name),
            vars_files=(Path(vars_file.name),),
        )
        delete_and_wait(server, cloud)


def test_synchronize_infrastructure() -> None:
    """Test `synchronize_infrastructure`."""
    cloud = connect()

    config_string = textwrap.dedent(
        f"""
        ---
        images:
            default: {IMAGE}
        network: {NETWORK}
        secgroups:
            - {SECGROUP}
        sshkey: {KEY}
        pubkeys:
          - "{ECDSAKey.generate(bits=384).get_base64()}"

        graceful: false

        deployment:
          worker-{NAME}:
            count: 3
            flavor: {FLAVOR}
        """
    )[1:]
    config = yaml.safe_load(config_string)
    try:
        # Verify initial status.
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        assert len(servers) == 0

        # Test adding servers.
        synchronize_infrastructure(
            config, cloud, user_data=None, vars_files=set(), dry_run=False
        )
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        assert len(servers) == 3

        # Test no changes.
        synchronize_infrastructure(
            config, cloud, user_data=None, vars_files=set(), dry_run=False
        )
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        assert len(servers) == 3

        # Test replace image.
        modified_config = deepcopy(config)
        modified_config["images"]["default"] = REPLACEMENT_IMAGE
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        assert len(servers) == 3
        assert all(server["image"]["id"] == IMAGE for server in servers)
        synchronize_infrastructure(
            modified_config,
            cloud,
            user_data=None,
            vars_files=set(),
            dry_run=False,
        )
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        assert len(servers) == 3
        assert all(
            server["image"]["id"] == REPLACEMENT_IMAGE for server in servers
        )

        # Test removing servers.
        modified_config = deepcopy(config)
        for group in config["deployment"]:
            modified_config["deployment"][group]["count"] = 0
        synchronize_infrastructure(
            modified_config,
            cloud,
            user_data=None,
            vars_files=set(),
            dry_run=False,
        )
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        assert len(servers) == 0

        # Test invalid date.
        modified_config = deepcopy(config)
        for group in config["deployment"]:
            modified_config["deployment"][group][
                "start"
            ] = datetime.date.today() - datetime.timedelta(days=2)
            modified_config["deployment"][group][
                "end"
            ] = datetime.date.today() - datetime.timedelta(days=1)
        synchronize_infrastructure(
            modified_config,
            cloud,
            user_data=None,
            vars_files=set(),
            dry_run=False,
        )
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        assert len(servers) == 0

        # Test valid date.
        modified_config = deepcopy(config)
        for group in config["deployment"]:
            modified_config["deployment"][group][
                "start"
            ] = datetime.date.today() - datetime.timedelta(days=1)
            modified_config["deployment"][group][
                "end"
            ] = datetime.date.today() + datetime.timedelta(days=1)
        synchronize_infrastructure(
            modified_config,
            cloud,
            user_data=None,
            vars_files=set(),
            dry_run=False,
        )
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        assert len(servers) == 3
    finally:
        servers = list(cloud.compute.servers())
        servers = [
            server
            for group in config["deployment"]
            for server in servers
            if filter_group(server, group)
        ]
        for server in servers:
            delete_and_wait(server, cloud)


if __name__ == "__main__":
    sys.exit(pytest.main())
