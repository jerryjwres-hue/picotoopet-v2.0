"""冻结方案中的领域枚举。"""

from enum import StrEnum


class TaskStatus(StrEnum):
    CREATED              = "Created"
    VALIDATING           = "Validating"
    QUEUED               = "Queued"
    RUNNING              = "Running"
    WAITING_FOR_TOOL     = "WaitingForTool"
    WAITING_FOR_APPROVAL = "WaitingForApproval"
    RETRYING             = "Retrying"
    COMPLETED            = "Completed"
    FAILED               = "Failed"
    CANCELLED            = "Cancelled"
    ARCHIVED             = "Archived"


class Classification(StrEnum):
    PUBLIC    = "PUBLIC"
    INTERNAL  = "INTERNAL"
    PROTECTED = "PROTECTED"


class CloudPolicy(StrEnum):
    LOCAL_ONLY   = "local_only"
    CLOUD_MANUAL = "cloud_manual"


class ApprovalStatus(StrEnum):
    PENDING  = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    EXPIRED  = "Expired"
