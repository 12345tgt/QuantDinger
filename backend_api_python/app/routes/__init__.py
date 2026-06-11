"""
API Routes Module — Agent Gateway + OpenAPI-registered human routes.
"""
from flask import Flask


def register_routes(app: Flask):
    """Register Agent Gateway and human web API (via flask-smorest)."""
    from app.openapi import init_openapi
    init_openapi(app)

    from app.routes.agent_v1 import register as register_agent_v1
    register_agent_v1(app)

    # Batch backtest web UI (plain Blueprint, not OpenAPI)
    from app.routes.batch_backtest import batch_bp
    app.register_blueprint(batch_bp)

    # Timing indicator management
    from app.routes.timing import timing_bp
    app.register_blueprint(timing_bp)
