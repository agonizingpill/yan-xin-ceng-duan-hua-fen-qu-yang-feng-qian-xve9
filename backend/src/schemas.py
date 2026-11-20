from pydantic import BaseModel,Field,ConfigDict
class Clean(BaseModel):model_config=ConfigDict(str_strip_whitespace=True,allow_inf_nan=False)
class Login(Clean):email:str;password:str
class HoleInput(Clean):
    code:str=Field(min_length=2,max_length=40)
    site:str=Field(min_length=2,max_length=120)
    total_depth:float=Field(gt=0,le=1000)
    cut_quota:float=Field(gt=0,le=100)
class RunInput(Clean):
    borehole_id:int
    code:str=Field(min_length=2,max_length=40)
    start_m:float=Field(ge=0)
    end_m:float=Field(gt=0)
    recovered_m:float=Field(ge=0)
class ReadingInput(Clean):
    borehole_id:int
    run_id:int
    depth_m:float=Field(ge=0)
    density:float=Field(ge=1,le=5)
    susceptibility:float=Field(ge=0,le=1000)
    velocity:float=Field(ge=500,le=9000)
class MissingInput(Clean):
    borehole_id:int
    start_m:float=Field(ge=0)
    end_m:float=Field(gt=0)
    reason:str=Field(default='',max_length=600)
class Reason(Clean):reason:str=Field(min_length=8,max_length=600)
class BoreholeRef(Clean):borehole_id:int
class LayerInput(Clean):
    start_m:float=Field(ge=0)
    end_m:float=Field(gt=0)
    lithology:str=Field(min_length=2,max_length=100)
    contact_note:str=Field(min_length=8,max_length=600)
class Layers(Clean):layers:list[LayerInput]=Field(min_length=1,max_length=40)
class SampleInput(Clean):
    borehole_id:int
    stratum_id:int
    code:str=Field(min_length=2,max_length=60)
    start_m:float=Field(ge=0)
    end_m:float=Field(gt=0)
    purpose:str=Field(min_length=2,max_length=200)
    destructive:bool=True
class SealInput(Clean):
    sample_id:int
    code:str=Field(min_length=4,max_length=60)
    reason:str=Field(default='',max_length=600)
class CustodyInput(Clean):
    seal_id:int
    receiver:str=Field(min_length=2,max_length=100)
    destination:str=Field(min_length=2,max_length=120)
    condition:str=Field(min_length=8,max_length=300)
class RevisionInput(Clean):
    borehole_id:int
    version:str=Field(min_length=2,max_length=40)
    note:str=Field(min_length=8,max_length=600)
class ReceiptBatchInput(Clean):
    borehole_id:int
    code:str=Field(min_length=2,max_length=60)
    sample_ids:list[int]=Field(min_length=2,max_length=8)
    note:str=Field(default='',max_length=600)
class ReceiptBagInput(Clean):
    nominal_sample_id:int
    code:str=Field(min_length=2,max_length=60)
    density:float=Field(gt=0,le=5)
    susceptibility:float=Field(ge=0,le=1000)
    velocity:float=Field(gt=500,le=9000)
class ReceiptCheckin(Clean):
    sample_ids:list[int]=Field(min_length=1,max_length=8)
class ReceiptPair(Clean):
    bag_id:int
    sample_id:int
class ReceiptVerify(Clean):
    reason:str=Field(min_length=8,max_length=600)
    assignment:list[ReceiptPair]=Field(min_length=1,max_length=8)
class ReceiptIssue(Clean):
    idempotency_key:str=Field(min_length=8,max_length=100)
