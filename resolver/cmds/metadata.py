from pathlib import Path
from typing import Optional

import click
import yaml

from resolver.cmds.click_types import YAML_OR_PATH_TYPE
from resolver.cmds.resolver_funcs import yaml_to_metadata
from resolver.puzzles.domain_constants import METADATA_FORMAT_VERSION
from resolver.types.domain_metadata import DomainMetadata, DomainMetadataDict


@click.group("metadata")
def metadata() -> None:
    """
    These commands allow you to create and validate domain metadata.
    """
    pass


@metadata.command("validate")
@click.option(
    "-m", "--metadata", "m_data", type=str, required=True, help="Path to YAML file or a YAML string with metadata"
)
def validate_metadata_cmd(m_data: str) -> None:
    """
    Validates the metadata given.
    :param m_data:
    :return:
    """
    import traceback

    try:
        yaml_to_metadata(m_data)
    except Exception:
        print(f"Metadata validation failed: {traceback.format_exc()}")
        return
    print("Metadata validation successful")


@metadata.command("create")
@click.option("-a", "--address", type=str, required=True, help="Main address of the domain")
@click.option(
    "-c",
    "--chain-records",
    type=YAML_OR_PATH_TYPE,
    default=dict(),
    help="Path to YAML file or a YAML string with chain records",
)
@click.option(
    "-d",
    "--dns-records",
    type=YAML_OR_PATH_TYPE,
    default=dict(),
    help="Path to YAML file or a YAML string with dns records",
)
@click.option(
    "-o",
    "--other-data",
    type=YAML_OR_PATH_TYPE,
    default=dict(),
    help="Path to YAML file or a YAML string with other data",
)
# create a path output option
@click.option(
    "-p",
    "--output",
    type=click.Path(exists=False),
    default=None,
    help="File to output the metadata to",
)
def metadata_create_cmd(
    address: str,
    chain_records: dict[str, str],
    dns_records: dict[str, str],
    other_data: dict[str, str],
    output: Optional[Path],
) -> None:
    """
    Creates metadata for you to use in the other commands.
    """
    import traceback

    dict_metadata = DomainMetadataDict(
        {  # create the metadata dictionary
            "metadata_version": METADATA_FORMAT_VERSION,
            "primary_address": address,
            "chain_records": chain_records,
            "dns_records": dns_records,
            "other_data": other_data,
        }
    )
    try:
        m_data = DomainMetadata.from_dict(dict_metadata)
    except Exception:
        print(f"Metadata creation failed: {traceback.format_exc()}")
        return
    output_str = yaml.dump(m_data.to_dict())
    if output is not None:
        with open(output, "w") as f:
            f.write(output_str)
    print(output_str)
