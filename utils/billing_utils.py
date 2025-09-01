from datetime import date, timedelta
from collections import defaultdict
from model import db, Contract, SchoolTerm, NonSchoolDay, InsetDay

def _month_bounds(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end

def _daterange(start, end):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)

def calculate_school_days_for_month(year: int, month: int):
    month_start, month_end = _month_bounds(year, month)

    schools = {c.school_name for c in Contract.query.distinct(Contract.school_name)}

    terms = SchoolTerm.query.filter(
        SchoolTerm.start_date <= month_end,
        SchoolTerm.end_date >= month_start
    ).all()

    non_school = {
        (r.date, r.school_name) for r in NonSchoolDay.query.filter(
            NonSchoolDay.date >= month_start,
            NonSchoolDay.date <= month_end
        ).all()
    }

    inset_days = defaultdict(set)
    for r in InsetDay.query.filter(
        InsetDay.date >= month_start,
        InsetDay.date <= month_end
    ).all():
        inset_days[r.school_name].add(r.date)

    results = {}

    for school in schools:
        billable_days = set()

        for term in terms:
            s = max(term.start_date, month_start)
            e = min(term.end_date, month_end)
            for d in _daterange(s, e):
                if d.weekday() < 5:
                    billable_days.add(d)

        billable_days = {
            d for d in billable_days
            if (d, school) not in non_school and d not in inset_days[school]
        }

        results[school] = len(billable_days)

    return results
