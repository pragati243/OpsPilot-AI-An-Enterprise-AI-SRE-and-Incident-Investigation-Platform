from dataclasses import dataclass

from app.models.remediation import RemediationRiskLevel


@dataclass(frozen=True)
class AllowedAction:
    action_type: str
    description: str
    risk_level: RemediationRiskLevel


# Every entry here always requires human approval — there is no
# auto-approved tier. Risk level informs how a future approval UI prioritizes
# review, not whether review happens at all: "the model can suggest a
# diagnosis; it cannot grant itself permission to perform an action."
ACTION_ALLOWLIST: dict[str, AllowedAction] = {
    "restart_service": AllowedAction(
        "restart_service", "Restart the service's process or pods", RemediationRiskLevel.MEDIUM
    ),
    "clear_cache": AllowedAction(
        "clear_cache", "Flush the service's cache layer", RemediationRiskLevel.LOW
    ),
    "scale_up": AllowedAction(
        "scale_up", "Increase replica or instance count", RemediationRiskLevel.LOW
    ),
    "scale_down": AllowedAction(
        "scale_down", "Decrease replica or instance count", RemediationRiskLevel.MEDIUM
    ),
    "rollback_deployment": AllowedAction(
        "rollback_deployment",
        "Roll back to the previously deployed version",
        RemediationRiskLevel.HIGH,
    ),
    "failover_database": AllowedAction(
        "failover_database", "Promote a standby database replica", RemediationRiskLevel.HIGH
    ),
}


class ActionNotAllowedError(Exception):
    pass


def check_action_allowed(action_type: str) -> AllowedAction:
    action = ACTION_ALLOWLIST.get(action_type)
    if action is None:
        raise ActionNotAllowedError(
            f"{action_type!r} is not an allowed remediation action type; "
            f"allowed types are: {', '.join(sorted(ACTION_ALLOWLIST))}"
        )
    return action
