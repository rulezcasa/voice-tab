"""Dates: the model describes WHEN in a small structured form, this code turns it into real dates.

Small models are good at turning words into structure ("10 days ago" -> days_ago=10) and bad at calendar
arithmetic ("what date is 10 days before Nov 20?"). So the agent never writes a date; it fills a `When`,
and resolve() works out the day (for logging) or the start/end range (for questions) from today in config.TZ.

    "yesterday"            -> When(days_ago=1)
    "10 days ago"          -> When(days_ago=10)
    "2 weeks ago"          -> When(weeks_ago=2)
    "a month ago"          -> When(months_ago=1)
    "Wednesday"            -> When(weekday="wed")                 most recent past Wednesday
    "last week Wednesday"  -> When(weekday="wed", weeks_back=1)   Wednesday of the previous Mon-Sun week
    "Nov 3" / "the 3rd"    -> When(month=11, day=3) / When(day=3)
    "last month"           -> When(period="month", offset=-1)     a range: Oct 1 .. Oct 31
    "this week"            -> When(period="week")                 Monday .. today
    "past 10 days"         -> When(last_n_days=10)                a range ending today
"""
import calendar
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_DAYS_BACK = 366  # an expense older than a year is almost certainly a misunderstanding


class DateError(ValueError):
    """The date can't be worked out or makes no sense. The message is safe to show the agent."""


class When(BaseModel):
    """When the money was spent, as the user said it. Fill only the fields the user's words give."""

    days_ago: int | None = Field(None, ge=0, description="'today'=0, 'yesterday'=1, '10 days ago'=10")
    weeks_ago: int | None = Field(None, ge=0, description="'a week ago'=1, '2 weeks ago'=2 (exact day, 7 days per week)")
    months_ago: int | None = Field(None, ge=0, description="'a month ago'=1 (same day of the month)")
    weekday: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"] | None = Field(
        None, description="a named day: 'Wednesday', 'last Wednesday', 'on Friday'")
    weeks_back: int = Field(0, ge=0, description="with weekday: 0 = the most recent one, "
                                                 "1 = 'last week Wednesday' (the previous Monday-Sunday week)")
    day: int | None = Field(None, ge=1, le=31, description="day of the month: 'the 3rd'=3")
    month: int | None = Field(None, ge=1, le=12, description="month number: 'November'=11")
    year: int | None = Field(None, description="only if the user says a year")
    period: Literal["day", "week", "month", "year"] | None = Field(
        None, description="questions about a whole period: 'this week', 'last month', 'this year'")
    offset: int = Field(0, le=0, description="with period: 0 = this one, -1 = last one, -2 = the one before")
    last_n_days: int | None = Field(None, ge=1, description="questions: 'past 10 days', 'last 30 days'")


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _shift_months(d: date, months: int) -> date:
    """Same day of the month, `months` later (negative = earlier), clamped to the month's last day."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _make(y: int, m: int, d: int) -> date:
    try:
        return date(y, m, d)
    except ValueError:
        raise DateError(f"{y}-{m:02d}-{d:02d} is not a real date")


def resolve(when: When | dict | None, today: date) -> tuple[date, date]:
    """(start, end) for `when`, measured from `today`. A single day comes back as (d, d)."""
    w = When.model_validate(when or {})

    if w.last_n_days is not None:
        return today - timedelta(days=w.last_n_days - 1), today

    if w.period is not None:
        if w.period == "day":
            d = today + timedelta(days=w.offset)
            return d, d
        if w.period == "week":
            start = _monday(today) + timedelta(weeks=w.offset)
            return start, min(start + timedelta(days=6), today)
        if w.period == "month":
            start = _shift_months(today.replace(day=1), w.offset)
            end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
            return start, min(end, today)
        start = date(today.year + w.offset, 1, 1)
        return start, min(date(start.year, 12, 31), today)

    if w.weekday is not None:
        wd = WEEKDAYS.index(w.weekday)
        weeks_back = w.weeks_back or w.weeks_ago or 0  # models write "last week Wednesday" both ways
        if weeks_back:
            d = _monday(today) - timedelta(weeks=weeks_back) + timedelta(days=wd)
        else:
            d = today - timedelta(days=(today.weekday() - wd) % 7 or 7)  # said on a Wednesday -> a week ago
        return d, d

    if w.day is not None or w.month is not None:
        if w.day is None:  # "in October": the whole month
            y = w.year or (today.year if w.month <= today.month else today.year - 1)
            start = _make(y, w.month, 1)
            return start, min(start.replace(day=calendar.monthrange(y, w.month)[1]), today)
        if w.month is None:  # "the 3rd": this month, or last month if that's still ahead
            d = _make(today.year, today.month, w.day) if w.day <= today.day else None
            if d is None:
                prev = _shift_months(today.replace(day=1), -1)
                d = _make(prev.year, prev.month, w.day)
            return d, d
        d = _make(w.year or today.year, w.month, w.day)
        if w.year is None and d > today:  # "Dec 28" said in November means last December
            d = _make(today.year - 1, w.month, w.day)
        return d, d

    if w.months_ago is not None:
        d = _shift_months(today, -w.months_ago)
        return d, d
    if w.weeks_ago is not None:
        d = today - timedelta(weeks=w.weeks_ago)
        return d, d
    d = today - timedelta(days=w.days_ago or 0)
    return d, d


def resolve_day(when: When | dict | None, today: date) -> date:
    """The single day an expense happened. Refuses ranges, future dates and dates over a year back."""
    start, end = resolve(when, today)
    if start != end:
        raise DateError(f"that is a range ({start} to {end}), not one day: ask which day it was")
    if start > today:
        raise DateError(f"{start} is in the future: ask which day it was")
    if (today - start).days > MAX_DAYS_BACK:
        raise DateError(f"{start} is more than a year ago: ask the user to confirm the date")
    return start


_PLACEHOLDER = re.compile(r":(start|end)\b")
# Dates the model worked out itself: literals like '2026-11-11' or SQL date maths. Both skip `when`.
_HANDMADE_DATE = re.compile(
    r"'\d{4}-\d{1,2}-\d{1,2}'|\b(curdate|current_date|now|sysdate|date_sub|date_add|subdate|adddate|interval)\b",
    re.I,
)


def fill_range(sql: str, when: When | dict | None, today: date) -> str:
    """Replace :start and :end in the agent's SQL with the dates `when` resolves to."""
    handmade = _HANDMADE_DATE.search(sql)
    if handmade:
        raise DateError(
            f"don't work out dates yourself ({handmade[0]}): pass `when` (e.g. {{\"last_n_days\": 10}}) "
            "and write e.spent_on BETWEEN :start AND :end"
        )
    if not _PLACEHOLDER.search(sql):
        if when:
            raise DateError("you passed `when` but the SQL never uses :start / :end")
        return sql
    if not when:
        raise DateError("the SQL uses :start / :end but no `when` was given")
    start, end = resolve(when, today)
    return _PLACEHOLDER.sub(lambda m: f"'{start if m[1] == 'start' else end}'", sql)


def say(d: date) -> str:
    """2026-11-11 -> 'Wed Nov 11'."""
    return f"{d:%a %b} {d.day}"
