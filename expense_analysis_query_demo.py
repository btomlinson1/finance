from insights_helpers import query_insights

# Example queries for the current expense DataFrame

print('Trend query:')
query_insights('how is my expense trending', df)

print('\nTop name query:')
query_insights('which name had the most expense', df, n=10)

print('\nForecast query:')
query_insights('forecast next 6 months', df)

print('\nCategory query:')
query_insights('show top categories', df)
