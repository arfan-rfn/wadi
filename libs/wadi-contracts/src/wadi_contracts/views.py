"""API view models: read-time enrichments over stored artifacts.

Views are DERIVED — never written to storage (the stored artifact stays pure,
§7). They live in the contracts package because every consumer of the API
(CLI, frontend via generated types, third parties via published schemas)
shares one definition.
"""

from pydantic import Field

from wadi_contracts.boundary import ServiceBoundary


class ServiceSummary(ServiceBoundary):
    """A service boundary plus counts aggregated at read time."""

    endpoint_count: int = Field(default=0, ge=0)
