import asyncio

import structlog
import typer

from adal.db.session import get_engine, init_db

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

app = typer.Typer(
    name="adal",
    help="ADAL — multi-agent scientific discovery framework",
    no_args_is_help=False,
)


async def _ensure_db():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: None)
    await init_db()


def _init_db_sync():
    try:
        asyncio.run(_ensure_db())
    except Exception:
        pass


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        tui()


@app.command()
def tui():
    """Launch the interactive Textual TUI."""
    _init_db_sync()
    from adal.tui.app import ADALApp
    app_instance = ADALApp()
    app_instance.run()


@app.command()
def api(
    host: str = typer.Option("0.0.0.0", help="Bind address"),
    port: int = typer.Option(8000, help="Listen port"),
):
    """Start the headless REST API server."""
    _init_db_sync()
    import uvicorn
    uvicorn.run("adal.api.app:app", host=host, port=port, log_level="info")


def main():
    app()


if __name__ == "__main__":
    main()
