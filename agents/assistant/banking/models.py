from typing import Any
from pydantic import BaseModel, ConfigDict


class _Flex(BaseModel):
    """Base with extra='allow' so unexpected fields from Claude pass through."""
    model_config = ConfigDict(extra="allow")


class IncomeSummary(_Flex):
    total_income: float
    sources: list[dict[str, Any]] = []


class SpendingAnalysis(_Flex):
    total_expenses: float
    net_savings_this_period: float
    categories: dict[str, Any] = {}
    anomalies: list[dict[str, Any]] = []
    month_over_month: dict[str, Any] = {}


class YearlyProgress(_Flex):
    target_savings_eur: float = 10_000.0
    savings_ytd: float
    remaining_target: float
    months_elapsed: int | None = None
    months_remaining: int | None = None
    expected_savings_to_date: float | None = None
    variance_from_expected: float | None = None
    required_monthly_savings: float
    trajectory: str
    on_track: bool


class InvestmentSignal(_Flex):
    ready_to_invest: bool
    available_amount: float
    note: str


class ChartData(_Flex):
    spending_by_category_pie: list[dict[str, Any]]
    income_vs_expenses_bar: list[dict[str, Any]]
    savings_progress_line: list[dict[str, Any]]


class BankAdviserResult(_Flex):
    meta: dict[str, Any]
    income_summary: IncomeSummary
    spending_analysis: SpendingAnalysis
    yearly_progress: YearlyProgress
    budget_next_month: dict[str, Any]
    investment_signal: InvestmentSignal
    recommendations: list[dict[str, Any]]
    savings_opportunities: list[dict[str, Any]]
    chart_data: ChartData
    reasoning: str | None = None
