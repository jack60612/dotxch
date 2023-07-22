from typing import Any, Optional

import click

from resolver.cmds.resolver_funcs import yaml_to_dict, yaml_to_metadata
from resolver.types.domain_metadata import DomainMetadata


class DomainMetadataParamType(click.ParamType):
    """
    A Click parameter type that returns a DomainMetadata Class from a yaml string or a yaml file.
    """

    name: str = "DomainMetadata"  # output type

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> DomainMetadata:
        if isinstance(value, DomainMetadata):  # required by click
            return value
        try:
            return yaml_to_metadata(value)
        except ValueError:
            self.fail("Value must be a yaml formatted string or a path pointing to a yaml file", param, ctx)


class YAMLOrPathParamType(click.ParamType):
    """
    A Click parameter type that returns a dict from a yaml string or a yaml file.
    """

    name: str = "dict"  # output type

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> dict[str, Any]:
        if isinstance(value, dict):  # required by click
            return value
        try:
            return yaml_to_dict(value)
        except ValueError:
            self.fail("Value must be a yaml formatted string or a path pointing to a yaml file", param, ctx)


DOMAIN_METADATA_TYPE = DomainMetadataParamType()
YAML_OR_PATH_TYPE = YAMLOrPathParamType()
