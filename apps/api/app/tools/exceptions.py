class ToolError(Exception):
    """Base class for domain errors raised by tool implementations.
    Callers (API routes today, a LangGraph tool-calling adapter later) are
    expected to catch this and turn it into a clean message rather than a
    stack trace.
    """


class ServiceNotFoundError(ToolError):
    """Raised for a service name/environment that doesn't exist in the
    caller's tenant. Deliberately generic — it must look identical whether
    the service belongs to no one or to a different tenant, so a tool can
    never be used to probe for another tenant's service names.
    """


class IncidentNotFoundError(ToolError):
    """Same tenant-isolation reasoning as ServiceNotFoundError."""
