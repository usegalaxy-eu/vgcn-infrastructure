#!/usr/bin/env python
"""Manage resources for the migration to HTCondor 23.

This script reads a resource definition (e.g. from resources.yaml) and produces
a new resource definition in which a (configurable) fraction of the cluster
resources are allocated to the secondary HTCondor cluster.
"""
import argparse
import sys
from copy import deepcopy
from math import ceil
from pathlib import Path

import yaml

"""Map HTCondor 8 images to the corresponding HTCondor 23 images.

The images "default", "gpu", "secure" and "alma" all have HTCondor 8 installed
and attach to the primary cluster after boot. The following mapping determines
what are the equivalent images running HTCondor 23 and that attach to the
secondary cluster after boot.
"""
IMAGE_MAPPING = {
    "default": "htcondor-secondary",
    "gpu": "htcondor-secondary-gpu",
    "secure": "htcondor-secondary",
    "alma": "htcondor-secondary",
    "htcondor-secondary": "htcondor-secondary",
    "htcondor-secondary-gpu": "htcondor-secondary-gpu",
}


def allocate_resources(resources: dict, fraction: float) -> dict:
    """Allocate resources to the secondary HTCondor cluster.

    Args:
        resources: Resource definition from `resources.yaml`.
        fraction: Fraction of resources to allocate to the secondary cluster.

    Returns:
        Modified resource definition with the corresponding fraction of
        resources allocated to the secondary cluster.

    Raises:
        ValueError: Invalid resource fraction provided.
    """
    if not 0 <= fraction <= 1:
        raise ValueError("'fraction' must be between 0 and 1")

    if fraction <= 0:
        return resources

    original = deepcopy(resources)
    modified = deepcopy(resources)

    primary_deployment = deepcopy(modified["deployment"])
    secondary_deployment = dict()
    for group, config in resources["deployment"].items():
        count = config["count"]

        if group.startswith("training") or "training" in config.get(
            "group", ""
        ):
            count_primary = ceil(config["count"] * (1 - fraction))
            count_secondary = count - count_primary
        else:
            count_primary = ceil(config["count"] * (1 - fraction))
            count_secondary = ceil(config["count"] * fraction)

        if count_primary > 0:
            primary_deployment[group] = {**config, "count": count_primary}
        else:
            del primary_deployment[group]
        if count_secondary > 0:
            secondary_deployment[f"{group}-htcondor-secondary"] = {
                **config,
                "count": count_secondary,
                "image": IMAGE_MAPPING[config.get("image", "default")],
                "secondary_htcondor_cluster": True,
            }
    modified["deployment"] = secondary_deployment | primary_deployment

    # We want to make use of a strategy that skips the modification of the
    # primary deployment, because it is preferred that VMs are not spawned due
    # to resources being exhausted rather than having VMs shut down in an
    # uncontrolled manner.
    #
    # Because VMs can get stuck, the number of available machines of each
    # flavor that is uncertain, and there are HTCondor groups that share the
    # same flavor, this is tricky.
    modified["deployment"] = (
        {
            group: config
            for group, config in modified["deployment"].items()
            if config["group"] == "upload" and config.get("count", 0) > 0
        }
        | {
            group: config
            for group, config in modified["deployment"].items()
            if config["group"] == "interactive" and config.get("count", 0) > 0
        }
        | {
            group: config
            for group, config in modified["deployment"].items()
            if "training" not in config["group"] and config.get("count", 0) > 0
        }
        | modified["deployment"]
        | original["deployment"]
    )

    return modified


def make_parser() -> argparse.ArgumentParser:
    """Command line interface for this script."""
    parser = argparse.ArgumentParser(
        prog="htcondor-migration",
        description="Manage resources for the migration to HTCondor 23.",
    )

    parser.add_argument(
        "-r",
        "--resources-file",
        dest="resources_file",
        type=Path,
        metavar="resources_file",
        help="resource definition file",
        default="resources.yaml",
    )
    parser.add_argument(
        "-f",
        "--fraction",
        dest="resource_fraction",
        type=float,
        metavar="resource_fraction",
        help="fraction of resources to be allocated to the secondary cluster",
        default=0.0,
    )
    parser.add_argument(
        "-o",
        "--output-file",
        dest="output_file",
        type=Path,
        metavar="output_file",
        help="output file, defaults to stdout",
    )

    return parser


if __name__ == "__main__":
    command_parser = make_parser()
    command_args = command_parser.parse_args()

    resource_definition = allocate_resources(
        resources=yaml.safe_load(open(command_args.resources_file)),
        fraction=command_args.resource_fraction,
    )
    resource_definition = yaml.dump(
        resource_definition,
        sort_keys=False,
    )

    print(
        resource_definition,
        file=open(output_file, "w")
        if (output_file := command_args.output_file)
        else sys.stdout,
    )
