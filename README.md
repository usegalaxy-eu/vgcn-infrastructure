# VGCN infrastructure management

This repository defines and manages the
[Virtual Galaxy Compute Nodes](https://github.com/usegalaxy-eu/vgcn) on
[bwCloud](https://www.bw-cloud.org/)/[de.NBI-cloud](https://www.denbi.de/)
for [usegalaxy.eu](https://usegalaxy.eu/)

The compute nodes are defined in [`resources.yaml`](#resourcesyaml), which 
conforms to [`schema.yaml`](schema.yaml).
[`userdata.yaml.j2`](userdata.yaml.j2) contains actions that will be run by
[cloud-init](https://cloudinit.readthedocs.io/en/latest/index.html) during the
first boot of the virtual machines (see 
[cloud-init docs](https://cloudinit.readthedocs.io/en/23.2.1/explanation/format.html)).

The Jenkins project 
[vgcn-infrastructure](https://build.galaxyproject.eu/job/usegalaxy-eu/job/vgcn-infrastructure/)
runs [`synchronize.py`](synchronize.py) periodically to deploy the configured
compute nodes.

## `resources.yaml`

This file defines the resources that should be allocated on the cluster, and it
is used to scale the infrastructure accordingly. An example is shown below

```yaml
training_event:
    count: 4
    flavor: c.c10m55
    tag: training-fallhts2017
    start: 2017-10-01
    end:  2017-10-02
```

The label `training_event` is arbitrary but must be unique in the file. We
specify that `count: 4` VMs of the 
[flavor](https://docs.openstack.org/nova/rocky/user/flavors.html)
c.c10m55 should be running. If there are fewer than this number, the 
[vgcn-infrastructure Jenkins project](https://build.galaxyproject.eu/job/usegalaxy-eu/job/vgcn-infrastructure/)
will launch [`synchronize.py`](synchronize.py) to ensure the actual capacity
matches the definition.

Additionally, `start` and `end` parameters may be supplied. VMs will be 
launched after the `start` date, and will be killed after the `end` date. This
permits defining resources ahead of the time they will be needed and releases
them automatically when they are no longer in use.

A formal definition of the schema is available within 
[`schema.yaml`](schema.yaml).

### Multiple flavors

Unfortunately, only a single flavor can be assigned to a group. As a workaround
to using multiple flavors in a group, just create N different groups with
different tags. E.g.

```
compute_nodes_small:
    count: 10
    flavor: c.c10m55
    tag: compute-small

compute_nodes_large:
    count: 10
    flavor: c.c24m120
    tag: compute-large
```

### Why is this not simply using Terraform?
> Because terraform couldn't downsize a cluster by chosing specific VMs, it had to be via count, which meant removing VMs from the "end".
thus I wrote ensure-enough [now synchronize.py] so we could remove unused VMs that weren't at the end of the count variable, and shrink the cluster more easily. hence non-linear numbering, it's part of the expectation that they'll get added or removed randomly, based on usage. (But then I spent most of the time with a fixed sized cluster because the Cloud isn't actually dynamic, at least in Freiburg. But that was before we were committed to taking up a large number of nodes) -- <cite>[@hexylena][1]</cite>

[1]: https://github.com/hexylena
