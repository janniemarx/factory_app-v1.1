from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from .pre_expansion import PreExpansion
from .production import CuttingProductionRecord
from .block import Block, BlockSession
from .operator import Operator
from .qc import QualityControl
from .boxing import BoxingSession, BoxingQualityControl
from .pr16_session import PR16Session, PR16TrimmingLog, PR16WrappingLog, PR16ResourceUsage, PR16WrappingProduction
from models.pr16_stash import PR16Stash
from .extrusion import (
    ExtrusionSession, ExtrudedProfile, Extruder,
    MaterialType, UsageUnit, ReadingType, ExtrusionProfileSettings,
)
from .maintenance import (
    MaintenanceJob, MaintenanceWorkSession, MaintenanceWorkSegment,
    MaintenanceStepLog, MaintenanceReview
)
from    .attendance import ( AttendanceDaily, AttendanceSyncRun, AttendanceEvent, WorkSchedule, LeaveRequest, OvertimeRequest, )
