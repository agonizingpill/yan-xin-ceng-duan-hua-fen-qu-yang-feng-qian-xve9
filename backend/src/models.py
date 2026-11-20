from sqlalchemy import String,Float,ForeignKey,JSON,Boolean,CheckConstraint,UniqueConstraint,Text
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(120),unique=True)
    password:Mapped[str]=mapped_column(String(256))
    role:Mapped[str]=mapped_column(String(20))
class Audit(Base):
    __tablename__='audit'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(120))
    action:Mapped[str]=mapped_column(Text)
    at:Mapped[str]=mapped_column(String(40))
class Borehole(Base):
    __tablename__='boreholes'
    __table_args__=(CheckConstraint('total_depth>0 AND cut_quota>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(40),unique=True)
    site:Mapped[str]=mapped_column(String(120))
    total_depth:Mapped[float]=mapped_column(Float)
    cut_quota:Mapped[float]=mapped_column(Float)
    state:Mapped[str]=mapped_column(String(20),default='open')
class CoreRun(Base):
    __tablename__='core_runs'
    __table_args__=(UniqueConstraint('borehole_id','code'),CheckConstraint('start_m>=0 AND end_m>start_m AND recovered_m>=0 AND recovered_m<=end_m-start_m'))
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    code:Mapped[str]=mapped_column(String(40))
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    recovered_m:Mapped[float]=mapped_column(Float)
class Reading(Base):
    __tablename__='readings'
    __table_args__=(UniqueConstraint('borehole_id','depth_m'),CheckConstraint('depth_m>=0 AND density>0 AND susceptibility>=0 AND velocity>0'))
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    run_id:Mapped[int]=mapped_column(ForeignKey('core_runs.id'))
    depth_m:Mapped[float]=mapped_column(Float)
    density:Mapped[float]=mapped_column(Float)
    susceptibility:Mapped[float]=mapped_column(Float)
    velocity:Mapped[float]=mapped_column(Float)
class MissingInterval(Base):
    __tablename__='missing_intervals'
    __table_args__=(CheckConstraint('start_m>=0 AND end_m>start_m'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    reason:Mapped[str]=mapped_column(String(600),default='')
    state:Mapped[str]=mapped_column(String(20),default='observed')
class Interpretation(Base):
    __tablename__='interpretations'
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    state:Mapped[str]=mapped_column(String(20),default='queued')
    evidence:Mapped[dict]=mapped_column(JSON,default=dict)
    error:Mapped[str]=mapped_column(String(600),default='')
class Stratum(Base):
    __tablename__='strata'
    __table_args__=(UniqueConstraint('interpretation_id','start_m'),CheckConstraint('start_m>=0 AND end_m>start_m'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    interpretation_id:Mapped[int]=mapped_column(ForeignKey('interpretations.id'))
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    lithology:Mapped[str]=mapped_column(String(100))
    contact_note:Mapped[str]=mapped_column(String(600))
class SampleInterval(Base):
    __tablename__='sample_intervals'
    __table_args__=(CheckConstraint('start_m>=0 AND end_m>start_m'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    stratum_id:Mapped[int]=mapped_column(ForeignKey('strata.id'))
    code:Mapped[str]=mapped_column(String(60),unique=True)
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    purpose:Mapped[str]=mapped_column(String(200))
    destructive:Mapped[bool]=mapped_column(Boolean,default=True)
    state:Mapped[str]=mapped_column(String(20),default='planned')
class Seal(Base):
    __tablename__='seals'
    id:Mapped[int]=mapped_column(primary_key=True)
    sample_id:Mapped[int]=mapped_column(ForeignKey('sample_intervals.id'))
    code:Mapped[str]=mapped_column(String(60),unique=True)
    previous_id:Mapped[int|None]=mapped_column(ForeignKey('seals.id'),nullable=True)
    state:Mapped[str]=mapped_column(String(20),default='intact')
    reason:Mapped[str]=mapped_column(String(600),default='')
    sealed_by:Mapped[str]=mapped_column(String(120))
    snapshot:Mapped[dict]=mapped_column(JSON)
class Custody(Base):
    __tablename__='custodies'
    __table_args__=(UniqueConstraint('seal_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    seal_id:Mapped[int]=mapped_column(ForeignKey('seals.id'))
    receiver:Mapped[str]=mapped_column(String(100))
    destination:Mapped[str]=mapped_column(String(120))
    condition:Mapped[str]=mapped_column(String(300))
    at:Mapped[str]=mapped_column(String(40))
class ColumnRevision(Base):
    __tablename__='column_revisions'
    __table_args__=(UniqueConstraint('borehole_id','version'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    version:Mapped[str]=mapped_column(String(40))
    note:Mapped[str]=mapped_column(String(600))
    state:Mapped[str]=mapped_column(String(20),default='draft')
    snapshot:Mapped[dict]=mapped_column(JSON,default=dict)
    frozen_by:Mapped[str]=mapped_column(String(120),default='')
class ReceiptBatch(Base):
    __tablename__='receipt_batches'
    __table_args__=(UniqueConstraint('borehole_id','code'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    code:Mapped[str]=mapped_column(String(60))
    note:Mapped[str]=mapped_column(String(600),default='')
    state:Mapped[str]=mapped_column(String(20),default='collecting')
    evidence:Mapped[dict]=mapped_column(JSON,default=dict)
    holds:Mapped[list]=mapped_column(JSON,default=list)
    hold_summary:Mapped[str]=mapped_column(String(1200),default='')
    verified_by:Mapped[str]=mapped_column(String(120),default='')
    verified_reason:Mapped[str]=mapped_column(String(600),default='')
    created_by:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[str]=mapped_column(String(40),default='')
class ReceiptSample(Base):
    __tablename__='receipt_samples'
    __table_args__=(UniqueConstraint('batch_id','sample_id'),UniqueConstraint('sample_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('receipt_batches.id'))
    sample_id:Mapped[int]=mapped_column(ForeignKey('sample_intervals.id'))
    seal_id:Mapped[int|None]=mapped_column(ForeignKey('seals.id'),nullable=True)
    checked_in:Mapped[bool]=mapped_column(Boolean,default=False)
    checked_in_at:Mapped[str]=mapped_column(String(40),default='')
    checked_in_by:Mapped[str]=mapped_column(String(120),default='')
class LabReceipt(Base):
    __tablename__='lab_receipts'
    __table_args__=(UniqueConstraint('batch_id','version'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('receipt_batches.id'))
    code:Mapped[str]=mapped_column(String(90),unique=True)
    version:Mapped[int]=mapped_column()
    idempotency_key:Mapped[str]=mapped_column(String(100),unique=True)
    received_by:Mapped[str]=mapped_column(String(120))
    at:Mapped[str]=mapped_column(String(40))
    bag_count:Mapped[int]=mapped_column()
    state:Mapped[str]=mapped_column(String(20),default='complete')
    void_reason:Mapped[str]=mapped_column(String(600),default='')
    snapshot:Mapped[dict]=mapped_column(JSON,default=dict)
class ReceiptBag(Base):
    __tablename__='receipt_bags'
    __table_args__=(UniqueConstraint('batch_id','code'),UniqueConstraint('batch_id','nominal_sample_id'),UniqueConstraint('batch_id','matched_sample_id'),CheckConstraint('density>0 AND susceptibility>=0 AND velocity>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('receipt_batches.id'))
    code:Mapped[str]=mapped_column(String(60))
    nominal_sample_id:Mapped[int]=mapped_column(ForeignKey('sample_intervals.id'))
    density:Mapped[float]=mapped_column(Float)
    susceptibility:Mapped[float]=mapped_column(Float)
    velocity:Mapped[float]=mapped_column(Float)
    measured_by:Mapped[str]=mapped_column(String(120),default='')
    measured_at:Mapped[str]=mapped_column(String(40),default='')
    matched_sample_id:Mapped[int|None]=mapped_column(ForeignKey('sample_intervals.id'),nullable=True)
    distance:Mapped[float|None]=mapped_column(Float,nullable=True)
    score:Mapped[float|None]=mapped_column(Float,nullable=True)
    receipt_id:Mapped[int|None]=mapped_column(ForeignKey('lab_receipts.id'),nullable=True)
