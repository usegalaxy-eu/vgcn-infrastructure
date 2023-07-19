import os
import sys

import yaml

os.environ.update(
    {
        "OS_AUTH_URL": "",
        "OS_USERNAME": "",
        "OS_PASSWORD": "",
        "OS_TENANT_ID": "",
    }
)


class MockAuth(object):
    @classmethod
    def load_from_options(cls, *args, **kwargs):
        return None


class MockKeystone(object):
    class session(object):
        @classmethod
        def Session(cls, *args, **kwargs):
            return "session"

    class loading(object):
        @classmethod
        def get_plugin_loader(cls, *args, **kwargs):
            return MockAuth()


class MockObject:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockNova(object):
    class client(object):
        @classmethod
        def Client(cls, version, session=None):
            return cls

        class networks(object):
            @classmethod
            def list(cls):
                return [MockObject(id=1, human_id="galaxy-net")]

        class flavors(object):
            @classmethod
            def list(cls):
                return [
                    MockObject(name="c.c10m55"),
                    MockObject(name="m1.xlarge"),
                ]

        class servers(object):
            servers = []

            @classmethod
            def list(cls):
                return cls.servers

            @classmethod
            def create(cls, **kwargs):
                cls.servers.append(MockObject(status="ACTIVE", **kwargs))

            @classmethod
            def _clear(cls, **kwargs):
                cls.servers = []


class MockGlance(object):
    class client(object):
        @classmethod
        def Client(cls, version, session=None):
            return cls

        class images(object):
            @classmethod
            def get(cls, image_id):
                return {"name": "vgcnbwc7-22"}

            @classmethod
            def list(cls):
                return [
                    MockObject(name="vgcnbwc7-21"),
                    MockObject(name="vgcnbwc7-22"),
                ]


# We fake this for testing purposes.
sys.modules["keystoneauth1"] = MockKeystone
sys.modules["novaclient"] = MockNova
sys.modules["glanceclient"] = MockGlance


import ensure_enough  # noqa

ensure_enough.CURRENT_IMAGE_NAME = "vgcnbwc7-22"
ensure_enough.CURRENT_IMAGE = {"id": "dead-beef-cafe"}


def test_launch_server():
    server = ensure_enough.launch_server("testing", "c.c10m55")
    assert server.name == "testing"
    server = ensure_enough.launch_server("testing2", "z.c10m55")
    assert server.name == "testing2"


def test_wait_for_state():
    server = ensure_enough.launch_server("testing", "c.c10m55")
    assert ensure_enough.wait_for_state("testing", "ACTIVE") == server


def test_nonconflicting_name():
    # Clear list of servers.
    sys.modules["novaclient"].client.servers._clear()

    ensure_enough.MAX_SERVER_POOL = 10
    for i in range(10):
        ensure_enough.launch_server("testing-%04d" % i, "c.c10m55")

    # TODO: find a better way to do this.
    # n = ensure_enough.non_conflicting_name('testing',
    # sys.modules['novaclient'].client.servers.list())
    # assert n == 'testing-0010', "%s != %s" % (n, 'testing-0010')

    # Now we'll fill that slot.
    ensure_enough.launch_server("testing-0010", "c.c10m55")

    # And the next one sohuld be a timestamp.
    n = ensure_enough.non_conflicting_name(
        "testing", sys.modules["novaclient"].client.servers.list()
    )
    # Good until 2020.
    assert n.startswith("testing-15")


def test_nonsimilar_resource_names():
    sys.modules["novaclient"].client.servers._clear()

    # Clear list of servers.
    ensure_enough.MAX_SERVER_POOL = 100
    for i in range(10):
        ensure_enough.launch_server("compute-general-%04d" % i, "c.c10m55")

    servers_rm, servers_ok = ensure_enough.identify_server_group(
        "compute-general"
    )
    assert len(servers_rm) == 0
    assert len(servers_ok) == 10

    servers_rm, servers_ok = ensure_enough.identify_server_group(
        "compute-highmem"
    )
    assert len(servers_rm) == 0
    assert len(servers_ok) == 0

    for i in range(4):
        ensure_enough.launch_server("compute-highmem-%04d" % i, "c.c10m55")

    servers_rm, servers_ok = ensure_enough.identify_server_group(
        "compute-general"
    )
    assert len(servers_rm) == 0
    assert len(servers_ok) == 10

    servers_rm, servers_ok = ensure_enough.identify_server_group(
        "compute-highmem"
    )
    assert len(servers_rm) == 0
    assert len(servers_ok) == 4


def test_similar_resource_names():
    with open("resources.yaml", "r") as handle:
        data = yaml.load(handle)

    resource_keys = data["deployment"].keys()

    for key in resource_keys:
        matching_prefixes = [
            other_key
            for other_key in resource_keys
            if other_key.startswith(key)
        ]
        assert len(matching_prefixes) == 1, (
            "(%s) both/all share a common prefix. This will result in "
            "machines being erronously deleted and re-added. If you must use "
            "this prefix, ensure they both have a suffix making them "
            "non-unique. (e.g. compute-general, compute-highmem)"
            % ", ".join(matching_prefixes)
        )
