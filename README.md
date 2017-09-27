# VGCN Infrastructure Management

This repository allows for definition and management of VGNC resources in the
bwCloud for usegalaxy.eu

## `resources.yaml`

This file defines resources that should be running on our cluster and scales
our infrastructure accordingly. The format is described fairly well within the
yaml file, but an example is below for reference:

```yaml
training_event:
    count: 4
    flavor: c.c10m55
    tag: training-fallhts2017
    start: 2017-10-01
    end:  2017-10-02
```

the label `training_event` is arbitrary but must be unique in the file. We
specify that we want `count=4` VMs of the flavor c.c10m55 running. If we have
fewer than this number, this project will launch enough to ensure we're at
capacity.

The `tag` must be specified and is used in constructing the name of the image.
For a tag of `upload`, images will be named `vgcnbwc-upload-{number}`

We additionally allow supplying a `start` and `end` parameter for the VMs.
Before this time the VMs will not be launched. After this time, the VMs will
all be (gracefully) killed on sight. This permits being rather lazy about
adding and removing defintions and we can be sure that resources are not
needlessly wasted.

## Multiple Flavors

If you want multiple flavors in a group, just create N different groups with different tags. E.g.

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

## LICENSE

GPLv3
