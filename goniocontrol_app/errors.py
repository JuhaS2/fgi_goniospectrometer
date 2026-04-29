class GoniocontrolError(Exception):
    """Base exception for goniocontrol application."""


class RecoverableHardwareError(GoniocontrolError):
    """Hardware operation failed but application can continue."""


class PreconditionError(GoniocontrolError):
    """Workflow preconditions are not met."""


class CalibrationMissingError(PreconditionError):
    """Required calibration artifact is missing."""

