# Main Entry - `main.py`

The primary entry point for the Store application. It initializes the components and starts the main loop/service.

## Purpose
- Orchestrate the startup sequence.
- Handle top-level configuration.
- Connect to the Database and Clients.

## Dependencies
- `orchestrator.py`
- `db.py`
- `etsy_client.py`
- `printify.py`

## Key Functions
- `main()`: Entry point.
- `init_app()`: Configures all modules.
