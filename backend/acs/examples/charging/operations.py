"""Optional operational records and transparent arithmetic. No enterprise integration."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from pydantic import Field, model_validator
from ...capabilities import Contract
from ...tools import immutable
from ...db import get
from .tools import outcome

class OperationalRecord(Contract):
    id: str = Field(min_length=1,max_length=200)
    version: int = Field(ge=1)
    kind: Literal['quote','permit','connection','budget','lead_time','working_calendar','maintenance_history','fault','maintenance_requirement']
    classification: Literal['verified','simulated','assumed']
    provenance: str = Field(min_length=1,max_length=2000)
    effective_from: date
    effective_until: date
    site_id: str | None = None
    currency: Literal['EUR'] = 'EUR'
    amount_ex_tax: Decimal | None = Field(default=None,ge=0)
    tax_rate: Decimal | None = Field(default=None,ge=0,le=1)
    quantity_unit: Literal['charger','point','site'] | None = None
    points_per_charger: int | None = Field(default=None,ge=1,le=100)
    lead_days: int | None = Field(default=None,ge=0,le=3650)
    approved: bool | None = None
    available_kw: float | None = Field(default=None,ge=0)
    duration_hours: float | None = Field(default=None,gt=0,le=168)
    due_date: date | None = None
    last_service_date: date | None = None
    note: str = Field(default='',max_length=4000)

    @model_validator(mode='after')
    def interval(self):
        if self.effective_until<self.effective_from:raise ValueError('Invalid effective interval')
        if self.kind=='quote' and (self.amount_ex_tax is None or self.tax_rate is None or self.quantity_unit is None):
            raise ValueError('Quote requires unit price, tax rate and quantity unit')
        return self

def import_record(db,record):
    immutable(db,'charging_operational',f'{record.id}:v{record.version}',record.model_dump(mode='json'))

class Records(Contract):
    record_ids: list[str] = Field(default_factory=list,max_length=30)

class Expansion(Records):
    quantity: int = Field(ge=1,le=10000)
    quantity_unit: Literal['charger','point','site']
    start_date: date
    deadline: date
    budget_including_tax: Decimal | None = Field(default=None,ge=0)
    required_kw: float | None = Field(default=None,gt=0)

def read(db,args):
    rows=[get(db,'charging_operational',ident) for ident in args.record_ids] if args.record_ids else [__import__('json').loads(r[0]) for r in db.execute("SELECT payload FROM documents WHERE kind='charging_operational' ORDER BY id LIMIT 30")]
    result=outcome(db,'charging.get_operational_inputs',dict(records=[r for r in rows if r],missing=[ident for ident,r in zip(args.record_ids,rows) if not r]),
        'available' if any(rows) else 'unavailable')
    result.origin='simulated_business' if any(r and r['classification']=='simulated' for r in rows) else 'human_preference'
    return result

def expansion(db,args):
    records=[OperationalRecord.model_validate(r) for ident in args.record_ids if (r:=get(db,'charging_operational',ident))]
    eligible=[r for r in records if r.effective_from<=args.start_date<=r.effective_until]
    quotes=[r for r in eligible if r.kind=='quote']
    if len(quotes)>1:
        return outcome(db,'charging.assess_expansion',{'candidates':[r.id+':v'+str(r.version) for r in quotes]},'needs_clarification',['Choose a single quote explicitly; alternatives are never silently combined.'])
    quote=quotes[0] if quotes else None
    cost=None;conversion=None;unknown=[]
    if quote:
        if quote.quantity_unit==args.quantity_unit:conversion=args.quantity
        elif args.quantity_unit=='point' and quote.quantity_unit=='charger' and quote.points_per_charger:
            conversion=(args.quantity+quote.points_per_charger-1)//quote.points_per_charger
        if conversion is not None:cost=quote.amount_ex_tax*conversion*(1+quote.tax_rate)
        else:unknown.append('No verified conversion between requested unit and quote unit')
    else:unknown.append('Missing effective quote')
    permits=[r for r in eligible if r.kind=='permit']
    lead=[r.lead_days for r in eligible if r.kind=='lead_time' and r.lead_days is not None]
    earliest=args.start_date+timedelta(days=sum(lead)) if lead else None
    connection=next((r for r in eligible if r.kind=='connection'),None)
    checks=dict(budget='unknown' if cost is None or args.budget_including_tax is None else ('satisfied' if cost<=args.budget_including_tax else 'violated'),
        deadline='violated' if args.deadline<args.start_date else ('unknown' if earliest is None else ('satisfied' if earliest<=args.deadline else 'violated')),
        permits='unknown' if not permits or any(r.approved is None for r in permits) else ('satisfied' if all(r.approved for r in permits) else 'violated'),
        connection='unknown' if not connection or connection.available_kw is None or args.required_kw is None else ('satisfied' if connection.available_kw>=args.required_kw else 'violated'))
    unknown += [k for k,v in checks.items() if v=='unknown']
    classification='simulated' if any(r.classification=='simulated' for r in eligible) else ('assumed' if any(r.classification=='assumed' for r in eligible) else 'verified inputs only')
    result=outcome(db,'charging.assess_expansion',dict(quantity=args.quantity,quantity_unit=args.quantity_unit,
        quoted_quantity=conversion,total_including_tax=str(cost) if cost is not None else None,currency='EUR',
        tax_basis='quoted unit price excluding tax; quoted tax rate applied once',earliest_date=str(earliest) if earliest else None,
        checks=checks,unknown=unknown,classification=classification,records=[r.id+':v'+str(r.version) for r in eligible],
        feasibility='violated' if 'violated' in checks.values() else 'unknown' if unknown or classification!='verified inputs only' else 'conditional'),
        limitations=['Business quantity is a target, not demand-justified allocation.',
            'Lead times are conservatively sequential calendar days. Working calendars and physical feasibility require verification.'])
    result.origin='simulated_business' if classification=='simulated' else 'derived_metric'
    return result
