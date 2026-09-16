from dataclasses import dataclass, field
from functools import lru_cache
from importlib import import_module
from typing import Callable

from django.conf import settings

from .contracts import InputModel


@dataclass(frozen=True)
class ReportDefinition:
    name: str
    title: str
    description: str
    input_model: type[InputModel]
    handler: Callable
    permission: str = "dashboard.view"
    persist: bool = True
    requires_single_currency: bool = True
    max_branches: int | None = 50
    metric_basis: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def report_registry():
    """Adding a report module doesn't require edits to OAuth or MCP dispatch."""
    registry = {}
    for module_path in settings.MCP_REPORT_MODULES:
        for report in import_module(module_path).REPORTS:
            if report.name in registry:
                raise ValueError(f"Duplicate analytics tool: {report.name}")
            registry[report.name] = report
    return registry
