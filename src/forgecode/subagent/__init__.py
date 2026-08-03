"""SubAgent 角色定义与 Catalog 加载。"""

from forgecode.subagent.catalog import Catalog, load_catalog
from forgecode.subagent.definition import Definition, Source
from forgecode.subagent.embed import builtin_definitions
from forgecode.subagent.parser import parse_definition, parse_file

__all__ = [
    "Catalog",
    "Definition",
    "Source",
    "builtin_definitions",
    "load_catalog",
    "parse_definition",
    "parse_file",
]
