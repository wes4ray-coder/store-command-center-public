# Orchestrator - `orchestrator.py`

The central brain of the Store application. It manages the flow of data between different clients and processes.

## Purpose
- Sequence the tasks (e.g., Fetch Trends -> Fix Prices -> Sync to Etsy).
- Manage state between different client calls.
- Handle errors and retries across multiple services.

## Key Components
- **Trends**: Fetching market data.
- **Price Fixer**: Logic for adjusting costs.
- **Etsy/Printify**: Outbound syncing.

## Flow
1. Start Trends analysis.
2. Pass data to Price Fixer.
3. Dispatch updated prices to Etsy/Printify.
