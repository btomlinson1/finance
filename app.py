from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st


def load_transactions(source) -> pd.DataFrame:
    """Load and normalize a transaction export with common column names."""
    if isinstance(source, (str, Path)):
        source_name = str(source)
        if source_name.lower().endswith(('.xlsx', '.xls')):
            frame = pd.read_excel(source)
        else:
            frame = pd.read_csv(source)
    else:
        file_bytes = source.getvalue()
        source_name = source.name
        if source_name.lower().endswith(('.xlsx', '.xls')):
            frame = pd.read_excel(BytesIO(file_bytes))
        else:
            frame = pd.read_csv(BytesIO(file_bytes))

    normalized = {str(column).strip().lower(): column for column in frame.columns}

    def find_column(*names):
        for name in names:
            if name in normalized:
                return normalized[name]
        return None

    date_column = find_column("date", "transaction date", "posted date")
    amount_column = find_column("amount", "amt", "value", "transaction amount")
    name_column = find_column("name", "merchant", "vendor", "payee", "description")
    category_column = find_column("category", "categories", "type of expense")
    parent_category_column = find_column("parent category", "parent_category")
    type_column = find_column("type", "transaction type")
    status_column = find_column("status", "transaction status")
    excluded_column = find_column("excluded", "exclude")
    tags_column = find_column("tags", "tag")
    account_column = find_column("account")
    recurring_column = find_column("recurring")

    if not date_column or not amount_column:
        raise ValueError("The file needs a date column and an amount column.")

    result = pd.DataFrame({
        "date": pd.to_datetime(frame[date_column], errors="coerce"),
        "amount": pd.to_numeric(frame[amount_column], errors="coerce"),
        "name": frame[name_column].fillna("Unknown") if name_column else "Unknown",
    })
    result["name"] = result["name"].astype(str).str.strip()
    result["category"] = (
        frame[category_column].fillna("").astype(str).str.strip()
        if category_column else ""
    )
    result["parent_category"] = (
        frame[parent_category_column].fillna("").astype(str).str.strip()
        if parent_category_column else ""
    )
    result["type"] = (
        frame[type_column].fillna("").astype(str).str.strip().str.lower()
        if type_column else "regular"
    )
    result["status"] = (
        frame[status_column].fillna("posted").astype(str).str.strip().str.lower()
        if status_column else "posted"
    )
    result["excluded"] = (
        frame[excluded_column].fillna(False).astype(str).str.lower().isin(["true", "1", "yes"])
        if excluded_column else False
    )
    result["tags"] = (
        frame[tags_column].fillna("").astype(str).str.strip()
        if tags_column else ""
    )
    result["account"] = (
        frame[account_column].fillna("Unknown").astype(str).str.strip()
        if account_column else "Unknown"
    )
    result["recurring"] = (
        frame[recurring_column].fillna(False).astype(str).str.lower().isin(["true", "1", "yes"])
        if recurring_column else False
    )
    result = result.dropna(subset=["date", "amount"])
    return result


def parse_affordability_question(question: str) -> float | None:
    match = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", question)
    return float(match.group(1).replace(",", "")) if match else None


def affordability_answer(transactions: pd.DataFrame, travel_cost: float) -> str:
    current_year = date.today().year
    year_data = transactions[transactions["date"].dt.year == current_year]
    spending = year_data[year_data["type"] == "regular"]["amount"].sum()
    income = year_data[year_data["type"] == "income"]["amount"].abs().sum()
    available = income - spending
    remaining = available - travel_cost
    if income == 0:
        return "I need income transactions in the file to estimate current-year cash flow."
    savings_rate = remaining / income
    verdict = "Yes" if remaining >= 0 else "Not from recorded cash flow"
    return (
        f"**{verdict}.** Recorded {current_year} cash flow leaves **${remaining:,.0f}** "
        f"after this trip. That implies a **{savings_rate:.1%}** cash savings rate "
        f"for the year so far."
    )


def category_spending_insights(transactions: pd.DataFrame, year: int) -> dict:
    """Analyze category spending vs 12-month historical average."""
    year_expenses = transactions[(transactions["date"].dt.year == year) & (transactions["type"] == "regular")]
    year_by_category = year_expenses.groupby("category")["amount"].sum().sort_values(ascending=False)
    
    # Compute 12-month average for each category
    all_expenses = transactions[transactions["type"] == "regular"].copy()
    all_expenses["year"] = all_expenses["date"].dt.year
    all_expenses["month"] = all_expenses["date"].dt.month
    monthly_by_category = all_expenses.groupby(["year", "month", "category"])["amount"].sum()
    
    insights = []
    for category, ytd_spend in year_by_category.items():
        category_data = all_expenses[all_expenses["category"] == category]
        if len(category_data) == 0:
            continue
        
        months_in_category = category_data.groupby(["year", "month"])["amount"].sum()
        avg_monthly = months_in_category.mean()
        
        if avg_monthly > 0:
            pct_change = ((ytd_spend / len(months_in_category)) - avg_monthly) / avg_monthly
        else:
            pct_change = 0
        
        insights.append({
            "category": category,
            "ytd_spend": ytd_spend,
            "monthly_avg": avg_monthly,
            "pct_change": pct_change,
            "months_in_year": len(year_expenses[year_expenses["category"] == category]["date"].dt.month.unique()),
        })
    
    return sorted(insights, key=lambda x: abs(x["pct_change"]), reverse=True)


def spending_anomalies(transactions: pd.DataFrame, year: int, threshold: float = 0.25) -> list:
    """Find categories with spending > threshold above or below recent average."""
    insights = category_spending_insights(transactions, year)
    anomalies = []
    
    for insight in insights:
        if abs(insight["pct_change"]) >= threshold:
            direction = "higher" if insight["pct_change"] > 0 else "lower"
            pct_str = f"{abs(insight['pct_change']):.0%}"
            anomalies.append({
                "text": f"**{insight['category']}** spending is {pct_str} {direction} than usual.",
                "pct_change": insight["pct_change"],
                "spend": insight["ytd_spend"],
            })
    
    return sorted(anomalies, key=lambda x: abs(x["pct_change"]), reverse=True)


def year_over_year_comparison(transactions: pd.DataFrame, current_year: int) -> dict:
    """Compare current year spending by category to previous year."""
    current = transactions[(transactions["date"].dt.year == current_year) & (transactions["type"] == "regular")]
    previous = transactions[(transactions["date"].dt.year == current_year - 1) & (transactions["type"] == "regular")]
    
    current_by_cat = current.groupby("category")["amount"].sum()
    previous_by_cat = previous.groupby("category")["amount"].sum()
    
    comparison = []
    all_cats = set(current_by_cat.index) | set(previous_by_cat.index)
    
    for cat in all_cats:
        curr = current_by_cat.get(cat, 0)
        prev = previous_by_cat.get(cat, 0)
        if prev > 0:
            pct_change = (curr - prev) / prev
        else:
            pct_change = 1.0 if curr > 0 else 0
        
        comparison.append({
            "category": cat,
            "current": curr,
            "previous": prev,
            "pct_change": pct_change,
        })
    
    return sorted(comparison, key=lambda x: abs(x["pct_change"]), reverse=True)


st.set_page_config(page_title="Ledger / personal finance", page_icon="$", layout="wide")

# Initialize session state for page navigation
if "current_page" not in st.session_state:
    st.session_state.current_page = "dashboard"

st.title("Ledger")
st.caption("A small, local-first view of where your money is going.")

# Page navigation
col1, col2 = st.columns(2)
with col1:
    if st.button("Dashboard", use_container_width=True, key="btn_dashboard"):
        st.session_state.current_page = "dashboard"
with col2:
    if st.button("Forecasting & FIRE", use_container_width=True, key="btn_forecasting"):
        st.session_state.current_page = "forecasting"

st.divider()

with st.sidebar:
    st.header("Load transactions")
    local_path = st.text_input(
        "Local CSV or Excel path",
        value="/Users/brandontomlinson/Downloads/transactions 38.csv",
    )
    uploaded_file = st.file_uploader("CSV or Excel export", type=["csv", "xlsx", "xls"])
    show_excluded = st.checkbox("Include excluded rows", value=True)
    show_pending = st.checkbox("Include pending rows", value=True)
    st.caption("Your file is processed in this app session and is not uploaded to a service.")

path_source = Path(local_path).expanduser() if local_path.strip() else None
source = path_source if path_source and path_source.is_file() else uploaded_file

if not source:
    st.info("Connect a local transaction file or upload an export to begin.")
    st.markdown("Expected columns: `date`, `amount`, and optionally `name` or `merchant`, `category`.")
    st.stop()

try:
    transactions = load_transactions(source)
except (ValueError, pd.errors.ParserError) as error:
    st.error(str(error))
    st.stop()

if transactions.empty:
    st.warning("No rows with valid dates and amounts were found.")
    st.stop()

latest_date = transactions["date"].max()
visible = transactions.copy()
if not show_excluded:
    visible = visible[(~visible["excluded"]) | (visible["type"] == "income")]
if not show_pending:
    visible = visible[visible["status"] != "pending"]

selected_account = st.sidebar.selectbox("Account", ["All"] + sorted(visible["account"].unique().tolist()))
if selected_account != "All":
    visible = visible[visible["account"] == selected_account]
selected_tag = st.sidebar.selectbox("Trip or tag", ["All"] + sorted([tag for tag in visible["tags"].unique() if tag]))
if selected_tag != "All":
    visible = visible[visible["tags"] == selected_tag]

# Month range selector
st.sidebar.divider()
st.sidebar.subheader("Time period")
available_months = sorted(visible["date"].dt.to_period("M").unique(), reverse=True)
if len(available_months) > 0:
    # Build hierarchical month structure by year
    months_by_year = {}
    for month in available_months:
        year = month.year
        if year not in months_by_year:
            months_by_year[year] = []
        months_by_year[year].append(month)
    
    # Create display options with hierarchy
    options_list = []
    values_list = []
    for year in sorted(months_by_year.keys(), reverse=True):
        # Add year header
        options_list.append(str(year))
        values_list.append(f"__YEAR__{year}")
        
        # Add months under year (sorted reverse chronologically)
        for month in sorted(months_by_year[year], reverse=True):
            options_list.append(f"  {month.strftime('%B %Y')}")
            values_list.append(month)
    
    # Multiselect for months
    selected_values = st.sidebar.multiselect(
        "Select month(s)",
        options=values_list,
        format_func=lambda x: options_list[values_list.index(x)] if isinstance(x, str) or hasattr(x, 'year') else str(x)
    )
    
    # Handle year selection logic: if a year is selected, select all its months
    selected_months = []
    year_selections = {}
    for val in selected_values:
        if isinstance(val, str) and val.startswith("__YEAR__"):
            year = int(val.split("__YEAR__")[1])
            year_selections[year] = True
        else:
            selected_months.append(val)
    
    # Add all months from selected years
    for year, _ in year_selections.items():
        selected_months.extend(months_by_year[year])
    
    # Remove duplicates and sort
    selected_months = sorted(set(selected_months), reverse=True)
    
    # If no months selected, default to latest month
    if not selected_months:
        selected_months = [available_months[0]]
    
    # Calculate date range from selected months
    month_starts = [m.start_time for m in selected_months]
    month_ends = [m.end_time for m in selected_months]
    month_start = min(month_starts)
    month_end = max(month_ends)
    
    # Store selected_month for comparison (use the first/latest selected month)
    selected_month = selected_months[0]
else:
    st.error("No data available for selected filters.")
    st.stop()

year_data = visible[(visible["date"] >= month_start) & (visible["date"] <= month_end)]
expenses = year_data[year_data["type"] == "regular"]
income = year_data[year_data["type"] == "income"]["amount"].abs().sum()
total_spend = expenses["amount"].sum()
savings = income - total_spend

if st.session_state.current_page == "dashboard":
    metric_columns = st.columns(4)
    metric_columns[0].metric("Total spend", f"${total_spend:,.0f}")
    metric_columns[1].metric("Total income", f"${income:,.0f}")
    metric_columns[2].metric("Net (income - spend)", f"${savings:,.0f}")
    metric_columns[3].metric("Transactions", f"{len(year_data):,}")

    st.subheader("Can I afford a purchase?")
    question = st.text_input("Ask a question", placeholder="Can I afford to spend $15,000 on travel this year?")
    if question:
        requested_amount = parse_affordability_question(question)
        if requested_amount is None:
            st.warning("Include a dollar amount, such as $15,000.")
        else:
            st.markdown(affordability_answer(transactions, requested_amount))

    st.divider()
    st.subheader("Spending insights")

    # Compare to same month last year
    comparison_month = selected_month - 12
    comparison_start = comparison_month.start_time
    comparison_end = comparison_month.end_time
    comparison_data = visible[(visible["date"] >= comparison_start) & (visible["date"] <= comparison_end)]
    comparison_expenses = comparison_data[comparison_data["type"] == "regular"]["amount"].sum()

    if len(comparison_data) > 0:
        st.markdown(f"**Compared to {comparison_month.strftime('%B %Y')}**")
        month_pct_change = ((abs(total_spend) - abs(comparison_expenses)) / abs(comparison_expenses)) if comparison_expenses != 0 else 0
        direction = "↑" if month_pct_change > 0 else "↓"
        st.markdown(f"{direction} **Spending: {abs(month_pct_change):.0%}** ({abs(total_spend):,.0f} vs {abs(comparison_expenses):,.0f})")
    else:
        st.info("No data available for comparison month.")

    st.divider()
    left_column, right_column = st.columns(2)
    with left_column:
        st.subheader("Monthly spend")
        monthly = expenses.assign(month=expenses["date"].dt.to_period("M")).groupby("month")["amount"].sum()
        st.bar_chart(monthly)

    with right_column:
        st.subheader("Where it goes")
        by_category = expenses.groupby("category")["amount"].sum().sort_values(ascending=False)
        st.bar_chart(by_category)

    st.subheader("Largest merchants")
    top_merchants = expenses.groupby("name")["amount"].agg(["sum", "count"]).sort_values("sum", ascending=False).head(10)
    top_merchants.columns = ["spend", "transactions"]
    st.dataframe(top_merchants.style.format({"spend": "${:,.2f}"}), width="stretch")

    st.divider()
    st.subheader("Category analysis")

    # Calculate 12-month rolling average ending at selected_month
    rolling_start = (selected_month - 12).start_time
    rolling_end = selected_month.end_time
    # Filter for regular expenses only, excluding internal transfers
    rolling_12m = visible[
        (visible["date"] >= rolling_start) & 
        (visible["date"] <= rolling_end) & 
        (visible["type"] == "regular")
    ]

    # Group by category and month to get monthly spending per category
    rolling_by_cat_month = rolling_12m.groupby([rolling_12m["date"].dt.to_period("M"), "category"])["amount"].sum()
    rolling_months_count = rolling_12m["date"].dt.to_period("M").nunique()

    # Calculate average per category over the 12-month period
    rolling_avg_by_cat = rolling_12m.groupby("category")["amount"].sum() / max(rolling_months_count, 1)

    # Build category analysis table
    cat_rows = []
    # Also filter year_data for consistency
    year_data_filtered = year_data[year_data["type"] == "regular"]
    for category in year_data_filtered["category"].unique():
        this_month_spend = abs(year_data_filtered[year_data_filtered["category"] == category]["amount"].sum())
        avg_spend = abs(rolling_avg_by_cat.get(category, 0))
        pct_vs_avg = ((this_month_spend - avg_spend) / avg_spend) if avg_spend != 0 else 0
        
        cat_rows.append({
            "Category": category,
            "This month": f"${this_month_spend:,.0f}",
            "12m avg": f"${avg_spend:,.0f}",
            "vs Avg": f"{pct_vs_avg:+.0%}",
        })

    if cat_rows:
        cat_analysis = pd.DataFrame(sorted(cat_rows, key=lambda x: float(x["This month"].replace("$", "").replace(",", "")), reverse=True)[:10])
        st.dataframe(cat_analysis, use_container_width=True)

    st.caption(f"Loaded {len(transactions):,} valid rows through {latest_date:%b %-d, %Y}. Viewing {selected_month.strftime('%B %Y')}.")

elif st.session_state.current_page == "forecasting":
    st.subheader("FIRE Analysis & Forecasting")
    st.markdown("5-year forward-looking P&L with rolling 12-month expense averages.")
    
    st.divider()
    st.markdown("### Financial Assumptions")
    
    # Input fields for assumptions
    col1, col2, col3 = st.columns(3)
    with col1:
        annual_pretax_income = st.number_input(
            "Annual pre-tax income ($)",
            value=80000,
            step=5000,
            key="annual_income_input"
        )
        monthly_pretax_income = annual_pretax_income / 12
    with col2:
        annual_deductions = st.number_input(
            "Annual deductions ($)",
            value=8000,
            step=500,
            key="annual_deduction_input"
        )
        monthly_deductions = annual_deductions / 12
    with col3:
        tax_rate = st.slider(
            "Effective tax rate (%)",
            min_value=0.0,
            max_value=50.0,
            value=25.0,
            step=0.5,
            key="tax_rate_slider"
        ) / 100.0
    
    st.divider()
    st.markdown("### Forecast Base Month")
    
    # Select base month for forecasting
    forecast_available_months = sorted(visible["date"].dt.to_period("M").unique(), reverse=True)
    if len(forecast_available_months) > 0:
        base_month = st.selectbox(
            "Select base month (forecast starts from next month)",
            options=forecast_available_months,
            format_func=lambda x: x.strftime("%B %Y"),
            key="forecast_base_month"
        )
        
        st.divider()
        st.markdown("### 5-Year Forward Forecast (P&L Statement)")
        
        # Build P&L forecast with categories as rows and months as columns
        # Include 12 months of ACTUAL data before base_month, then 60 months forward forecast
        months_list = []
        
        # Add actual data months (12 months prior, including base_month)
        current_month = base_month - 11
        for i in range(12):
            months_list.append(current_month)
            current_month = current_month + 1
        
        # Add forecast months (60 months after base_month)
        current_month = base_month + 1
        for i in range(60):
            months_list.append(current_month)
            current_month = current_month + 1
        
        # Build P&L rows
        pl_data = {}
        
        # Income row (constant across months)
        pl_data["Income"] = []
        for _ in months_list:
            taxable = monthly_pretax_income - monthly_deductions
            taxes = max(0, taxable * tax_rate)
            after_tax = monthly_pretax_income - taxes
            pl_data["Income"].append(after_tax)
        
        # Expense categories - get from actual data
        all_categories = sorted(visible[visible["type"] == "regular"]["category"].unique().tolist())
        for category in all_categories:
            pl_data[category] = []
        
        # Get the latest date in our data
        latest_data_date = visible["date"].max()
        
        # Calculate expenses for each month
        for month_idx, month in enumerate(months_list):
            if month <= base_month:
                # For actual data months: sum actual transactions in that month
                month_start = month.start_time
                month_end = month.end_time
                month_data = visible[
                    (visible["date"] >= month_start) & 
                    (visible["date"] <= month_end) & 
                    (visible["type"] == "regular")
                ]
                
                for category in all_categories:
                    cat_data = month_data[month_data["category"] == category]
                    cat_expense = abs(cat_data["amount"].sum()) if len(cat_data) > 0 else 0
                    pl_data[category].append(cat_expense)
            else:
                # For forecast months: use rolling 12-month average that includes actual + previously calculated forecast
                # Build a 12-month window from (month - 12) to (month - 1)
                window_start_idx = month_idx - 12
                window_end_idx = month_idx
                
                for category in all_categories:
                    category_values = []
                    
                    # Collect values from the 12-month window
                    for i in range(window_start_idx, window_end_idx):
                        if 0 <= i < len(months_list):
                            window_month = months_list[i]
                            
                            if window_month <= base_month:
                                # Use actual transaction data for this month
                                month_start = window_month.start_time
                                month_end = window_month.end_time
                                month_data = visible[
                                    (visible["date"] >= month_start) & 
                                    (visible["date"] <= month_end) & 
                                    (visible["type"] == "regular")
                                ]
                                cat_data = month_data[month_data["category"] == category]
                                cat_expense = abs(cat_data["amount"].sum()) if len(cat_data) > 0 else 0
                            else:
                                # Use previously calculated forecast value
                                cat_expense = pl_data[category][i]
                            
                            category_values.append(cat_expense)
                    
                    # Average the 12-month window
                    avg_expense = sum(category_values) / len(category_values) if category_values else 0
                    pl_data[category].append(avg_expense)
        
        # Create forecast dataframe with yearly totals
        forecast_df_dict = {"Category": ["Income"] + all_categories + ["Total Expenses", "Net Savings"]}
        
        # Group months by year
        years_data = {}
        for i, month in enumerate(months_list):
            year = month.year
            if year not in years_data:
                years_data[year] = {"months": [], "indices": []}
            years_data[year]["months"].append(month)
            years_data[year]["indices"].append(i)
        
        # Create yearly columns
        for year in sorted(years_data.keys()):
            year_label = str(year)
            indices = years_data[year]["indices"]
            
            # Sum income for the year
            year_income = sum([pl_data["Income"][i] for i in indices])
            col_values = [year_income]
            
            # Sum each expense category for the year
            year_expenses = 0
            for category in all_categories:
                cat_year_sum = sum([pl_data[category][i] for i in indices])
                col_values.append(cat_year_sum)
                year_expenses += cat_year_sum
            
            col_values.append(year_expenses)
            col_values.append(year_income - year_expenses)
            
            forecast_df_dict[year_label] = col_values
        
        # Create and display forecast dataframe
        forecast_display_df = pd.DataFrame(forecast_df_dict)
        
        # Display forecast
        st.dataframe(forecast_display_df.map(lambda x: f"${x:,.0f}" if isinstance(x, (int, float)) else x), use_container_width=True, height=600)
        
        # Calculate 5-year summary from forecast data
        st.divider()
        st.markdown("### 5-Year Summary")
        
        # Sum income and expenses across 60 months
        total_income_5yr = sum(pl_data["Income"])
        total_expenses_5yr = sum([sum(pl_data[cat]) for cat in all_categories])
        total_savings = total_income_5yr - total_expenses_5yr
        avg_monthly_savings = total_savings / 60 if total_savings > 0 else 0
        avg_savings_rate = (total_savings / total_income_5yr) if total_income_5yr > 0 else 0
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total income (5yr)", f"${total_income_5yr:,.0f}")
        with col2:
            st.metric("Total expenses (5yr)", f"${total_expenses_5yr:,.0f}")
        with col3:
            st.metric("Total savings (5yr)", f"${total_savings:,.0f}")
        with col4:
            st.metric("Avg monthly savings", f"${avg_monthly_savings:,.0f}")
        
        # FIRE calculation
        st.divider()
        st.markdown("### FIRE Projections")
        
        avg_monthly_expense = total_expenses_5yr / 60
        fire_number = avg_monthly_expense * 12 / 0.04  # 4% safe withdrawal rate
        st.markdown(f"**FIRE number (4% SWR):** ${fire_number:,.0f}")
        
        if avg_monthly_savings > 0:
            years_to_fire = fire_number / (avg_monthly_savings * 12)
            st.markdown(f"**Years to FIRE (at forecast rate):** {years_to_fire:.1f} years")
            fire_date = base_month.year + int(years_to_fire) + 1
            st.markdown(f"**Potential FIRE year:** ~{fire_date}")
        else:
            st.warning("Average monthly savings is zero or negative. FIRE timeline cannot be calculated.")
