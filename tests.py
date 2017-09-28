import sys
import os
os.environ.update({
    'OS_AUTH_URL': "",
    'OS_USERNAME': "",
    'OS_PASSWORD': "",
    'OS_TENANT_ID': "",
})


class MockAuth(object):
    @classmethod
    def load_from_options(cls, *args, **kwargs):
        return None


class MockKeystone(object):

    class session(object):
        @classmethod
        def Session(cls, *args, **kwargs):
            return 'session'

    class loading(object):
        @classmethod
        def get_plugin_loader(cls, *args, **kwargs):
            return MockAuth()


class MockObject:
    def __init__(self, **kwargs):
        for (k, v) in kwargs.items():
            setattr(self, k, v)


class MockNova(object):
    class client(object):

        @classmethod
        def Client(cls, version, session=None):
            return cls

        class networks(object):
            @classmethod
            def list(cls):
                return [MockObject(id=1, human_id='galaxy-net')]

        class flavors(object):
            @classmethod
            def list(cls):
                return [MockObject(name='c.c10m55'), MockObject(name='m1.xlarge')]

        class servers(object):
            servers = []

            @classmethod
            def list(cls):
                return []

            @classmethod
            def create(cls, **kwargs):
                cls.servers.append(MockObject(**kwargs))


class MockGlance(object):
    class client(object):

        @classmethod
        def Client(cls, version, session=None):
            return cls

        class images(object):
            @classmethod
            def list(cls):
                return [MockObject(name='vgcnbwc7-21'), MockObject(name='vgcnbwc7-22')]


# We fake this for testing purposes.
sys.modules['keystoneauth1'] = MockKeystone
sys.modules['novaclient'] = MockNova
sys.modules['glanceclient'] = MockGlance


import ensure_enough  # noqa
