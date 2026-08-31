# Personal Expense Insights

This project is a simple Python-based notebook for analyzing personal expense transactions from an Excel file.

## Setup

1. Create a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Open `expense_analysis.ipynb` in VS Code or Jupyter.

## Usage

### Local dashboard

Install the dependencies and launch the first interactive finance slice:

```bash
pip install -r requirements.txt
streamlit run app.py
```

### Plaid setup

Create a Plaid developer account, then set these environment variables locally before launching the app:

```bash
export PLAID_ENV=sandbox
export PLAID_CLIENT_ID=your_client_id
export PLAID_SECRET=your_sandbox_secret
streamlit run app.py
```

The current app only reports whether Plaid is configured. The next integration step is Plaid Link, followed by securely exchanging the one-time public token for an access token and fetching balances. Never commit the secret or an access token; `.env` is ignored if you choose to load variables from a local file.

Enter a local CSV or Excel path in the sidebar, or upload an export with `date` and `amount` columns. The dashboard defaults to `/Users/brandontomlinson/Downloads/transactions 38.csv` and reads it directly from your Mac. It recognizes the Copilot Money fields `name`, `category`, `parent category`, `status`, `excluded`, `tags`, `type`, `account`, and `recurring`. `regular` rows are expenses and are summed as signed amounts so refunds reduce spending, `income` rows are income, and `internal transfer` rows are excluded from both. The dashboard includes excluded and pending rows by default to match the notebook's Excel-style total; both can be toggled off. Tags and accounts can be used as dashboard filters.

- Update the `excel_path` variable in `expense_analysis.ipynb` to point to your file:
  `/Users/brandontomlinson/Library/Mobile Documents/com~apple~CloudDocs/Excel/Copilot Model Apr 26.xlsx`
- Run the notebook cells to load the data and generate insights.

## Files

- `expense_analysis.ipynb`: notebook to load and explore the Excel file.
- `requirements.txt`: Python dependencies.
- `.gitignore`: ignore notebook checkpoints and virtual environment.
