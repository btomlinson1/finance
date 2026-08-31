"""Helper functions for quick financial insights to use from a notebook.

Functions:
- summarize_trend(df, date_col='date', amount_col='amount') -> dict + DataFrame
- top_names(df, name_col='name', amount_col='amount', n=10) -> DataFrame
- forecast_monthly(df, date_col='date', amount_col='amount', periods=6) -> Series
- query_insights(question, df, **kwargs) -> prints/returns results (simple rule-based)

No external ML packages required; uses pandas and numpy.
"""

from typing import Optional
import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns


def _resolve_column(df: pd.DataFrame, candidates):
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _filter_regular_expenses(df: pd.DataFrame):
    if 'type' in df.columns:
        return df[df['type'] == 'regular']
    return df


def summarize_trend(df: pd.DataFrame, date_col: str = 'date', amount_col: str = 'amount'):
    """Return basic trend metrics and monthly totals.

    Returns a dict with monthly totals Series and simple trend summary.
    """
    d = df.copy()
    d = _filter_regular_expenses(d)
    if date_col not in d.columns or amount_col not in d.columns:
        raise ValueError('date or amount column not found')
    d[date_col] = pd.to_datetime(d[date_col], errors='coerce')
    d[amount_col] = pd.to_numeric(d[amount_col], errors='coerce')
    monthly = d.groupby(d[date_col].dt.to_period('M'))[amount_col].sum().sort_index()

    # Compute simple linear trend on monthly totals
    if len(monthly) >= 2:
        x = np.arange(len(monthly))
        y = monthly.values
        coef = np.polyfit(x, y, 1)
        slope = coef[0]
        intercept = coef[1]
        trend_desc = f"Linear trend slope={slope:.2f} per-month (intercept {intercept:.2f})"
    else:
        slope = np.nan
        trend_desc = 'Not enough data for trend'

    # month-over-month change (last two months)
    mom = None
    if len(monthly) >= 2:
        mom = (monthly.iloc[-1] - monthly.iloc[-2])
    # year-over-year comparison for last month if available
    yoy = None
    if len(monthly) >= 13:
        yoy = monthly.iloc[-1] - monthly.iloc[-13]

    return {
        'monthly': monthly,
        'slope': slope,
        'trend_desc': trend_desc,
        'mom_change': mom,
        'yoy_change': yoy,
    }


def top_names(df: pd.DataFrame, name_col: str = 'name', amount_col: str = 'amount', n: int = 10):
    """Return top n names by total expense (descending)."""
    if name_col not in df.columns or amount_col not in df.columns:
        raise ValueError('name or amount column not found')
    d = _filter_regular_expenses(df.copy())
    d[amount_col] = pd.to_numeric(d[amount_col], errors='coerce')
    summary = d.groupby(name_col)[amount_col].sum().sort_values(ascending=False).head(n)
    return summary


def forecast_monthly(df: pd.DataFrame, date_col: str = 'date', amount_col: str = 'amount', periods: int = 6):
    """Simple linear-projection forecast for next `periods` months using monthly totals.

    Uses linear regression on month index to forecast future monthly totals.
    Returns a pandas Series indexed by Period (M).
    """
    d = _filter_regular_expenses(df.copy())
    if date_col not in d.columns or amount_col not in d.columns:
        raise ValueError('date or amount column not found')
    d[date_col] = pd.to_datetime(d[date_col], errors='coerce')
    d[amount_col] = pd.to_numeric(d[amount_col], errors='coerce')
    monthly = d.groupby(d[date_col].dt.to_period('M'))[amount_col].sum().sort_index()
    if len(monthly) < 2:
        raise ValueError('Not enough monthly data for forecasting')

    x = np.arange(len(monthly))
    y = monthly.values
    coef = np.polyfit(x, y, 1)
    slope, intercept = coef[0], coef[1]

    future_x = np.arange(len(monthly), len(monthly) + periods)
    preds = intercept + slope * future_x

    # build future Period index
    last_period = monthly.index[-1]
    future_periods = [last_period + i for i in range(1, periods + 1)]
    forecast = pd.Series(preds, index=future_periods)
    forecast.index = pd.PeriodIndex(forecast.index, freq='M')
    return forecast


def query_insights(question: str, df: pd.DataFrame, **kwargs):
    """A small rule-based natural-language wrapper for common finance questions.

    Recognized intent:
    - trend / trending / how is my spending
    - forecast / predict
    - name / vendor / merchant top spend
    - category breakdown
    """
    q = question.lower()
    if re.search(r'forecast|predict|projection|next \d+ months', q):
        periods = kwargs.get('periods', 6)
        parsed = re.search(r'next (\d+) months', q)
        if parsed:
            periods = int(parsed.group(1))
        f = forecast_monthly(df, kwargs.get('date_col', 'date'), kwargs.get('amount_col', 'amount'), periods=periods)
        print(f"Forecast next {periods} months:")
        print(f)
        return f

    if re.search(r'trend|trending|spend|spending|how is my expense|how is my spending', q):
        s = summarize_trend(df, kwargs.get('date_col', 'date'), kwargs.get('amount_col', 'amount'))
        print('Trend summary:')
        print(s['trend_desc'])
        print('Most recent month change:', s['mom_change'])
        if s['yoy_change'] is not None:
            print('Year-over-year change for last month:', s['yoy_change'])
        if kwargs.get('display', True):
            print('\nMonthly totals (last 12):')
            print(s['monthly'].tail(12))
        return s

    if re.search(r'which name|top name|most expense|largest expense|top vendor|largest vendor|top merchant', q):
        top = top_names(df, kwargs.get('name_col', 'name'), kwargs.get('amount_col', 'amount'), kwargs.get('n', 5))
        print('Top names by total expense:')
        print(top)
        return top

    if re.search(r'category|categories|expense by category', q):
        cat_col = kwargs.get('category_col', 'category')
        if cat_col not in df.columns:
            raise ValueError('Category column not found')
        d = _filter_regular_expenses(df.copy())
        cat = d.groupby(cat_col)[kwargs.get('amount_col', 'amount')].sum().sort_values(ascending=False)
        print('Top categories:')
        print(cat.head(10))
        return cat

    print("Sorry, I don't understand the question. Try 'how is my expense trending', 'which name had the most expense', 'forecast next 6 months', or 'show top categories'.")
    return None


def plot_monthly_trend(df: pd.DataFrame, date_col: str = 'date', amount_col: str = 'amount', title: Optional[str] = None):
    """Plot monthly totals as a line chart."""
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors='coerce')
    d[amount_col] = pd.to_numeric(d[amount_col], errors='coerce')
    monthly = d.groupby(d[date_col].dt.to_period('M'))[amount_col].sum().sort_index()
    idx = monthly.index.to_timestamp()
    plt.figure(figsize=(10,4))
    sns.lineplot(x=idx, y=monthly.values)
    plt.xlabel('Month')
    plt.ylabel('Total Spend')
    plt.title(title or 'Monthly Spend')
    plt.tight_layout()
    plt.show()


def plot_forecast(forecast_series: pd.Series, title: Optional[str] = None):
    """Plot forecasted monthly totals (Series indexed by Period)."""
    idx = forecast_series.index.to_timestamp()
    plt.figure(figsize=(10,4))
    sns.barplot(x=idx, y=forecast_series.values)
    plt.xlabel('Month')
    plt.ylabel('Forecasted Spend')
    plt.title(title or 'Forecasted Monthly Spend')
    plt.tight_layout()
    plt.show()
