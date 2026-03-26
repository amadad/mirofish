"""
MiroFish Backend - Flask Application Factory
"""

import os
import warnings

# Suppress multiprocessing resource_tracker warnings (from third-party libs like transformers)
# Must be set before all other imports
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request, send_from_directory
from flask_cors import CORS

from .config import Config
from .services.graph_storage import JSONStorage, KuzuDBStorage
from .utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Flask application factory function"""
    frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../frontend/dist'))
    app = Flask(__name__, static_folder=frontend_dist if os.path.isdir(frontend_dist) else None)
    app.config.from_object(config_class)
    
    # Set JSON encoding: ensure non-ASCII characters are displayed directly (instead of \uXXXX format)
    # Flask >= 2.3 uses app.json.ensure_ascii, older versions use JSON_AS_ASCII config
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False
    
    # Set up logging
    logger = setup_logger('mirofish')
    
    # Only print startup info in the reloader subprocess (avoid printing twice in debug mode)
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend starting...")
        logger.info("=" * 50)
    
    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": app.config.get('CORS_ORIGINS', [])}})

    storage_backend = app.config.get("GRAPH_BACKEND", "kuzu")
    if storage_backend == "json":
        app.extensions["graph_storage"] = JSONStorage(data_dir=app.config["DATA_DIR"])
    else:
        app.extensions["graph_storage"] = KuzuDBStorage(db_path=app.config["KUZU_DB_PATH"])
    
    # Initialize hybrid search (semantic + BM25 via Qdrant embedded)
    try:
        from .services.hybrid_search import HybridSearchService
        hybrid_db_path = os.path.join(os.path.dirname(__file__), "../data/hybrid_search")
        app.extensions["hybrid_search"] = HybridSearchService(
            db_path=hybrid_db_path,
            model_name=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
        )
        if should_log_startup:
            logger.info("Hybrid search enabled (Qdrant + BGE-M3)")
    except Exception as e:
        app.extensions["hybrid_search"] = None
        if should_log_startup:
            logger.warning("Hybrid search disabled: %s", e)

    # Register simulation process cleanup (ensure all simulation processes are terminated on server shutdown)
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Simulation process cleanup registered")
        logger.info("Graph storage backend: %s", type(app.extensions["graph_storage"]).__name__)
    
    # Request logging middleware
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"Request: {request.method} {request.path}")
        if app.config.get('DEBUG') and request.content_type and 'json' in request.content_type:
            logger.debug(f"Request body: {request.get_json(silent=True)}")
    
    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"Response: {response.status_code}")
        return response
    
    # Register blueprints
    from .api import graph_bp, simulation_bp, report_bp, knesset_bp, knesset_data_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(knesset_bp)
    app.register_blueprint(knesset_data_bp)

    # Initialize Pinecone search service
    try:
        from .services.pinecone_search import PineconeSearchService
        pinecone_service = PineconeSearchService()
        if pinecone_service.is_available:
            app.extensions["pinecone_search"] = pinecone_service
            if should_log_startup:
                logger.info("Pinecone search enabled")
        else:
            app.extensions["pinecone_search"] = None
    except Exception as e:
        app.extensions["pinecone_search"] = None
        if should_log_startup:
            logger.warning("Pinecone search disabled: %s", e)

    # Initialize Knesset Data Daemon (background collection)
    if os.environ.get("KNESSET_DAEMON_ENABLED", "").lower() in ("1", "true", "yes"):
        try:
            from .services.knesset.data_daemon import KnessetDataDaemon
            daemon = KnessetDataDaemon(
                graph_storage=app.extensions.get("graph_storage"),
                pinecone_service=app.extensions.get("pinecone_search"),
            )
            app.extensions["knesset_daemon"] = daemon
            daemon.start()
            if should_log_startup:
                logger.info("Knesset Data Daemon started (background collection)")
        except Exception as e:
            app.extensions["knesset_daemon"] = None
            if should_log_startup:
                logger.warning("Knesset Data Daemon failed to start: %s", e)
    else:
        app.extensions["knesset_daemon"] = None
    
    # Health check
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_frontend(path):
        if path.startswith('api/') or path == 'health':
            return {'error': 'Not found'}, 404

        static_folder = app.static_folder
        if not static_folder or not os.path.isdir(static_folder):
            return {'error': 'Frontend not built'}, 404

        if path:
            asset_path = os.path.join(static_folder, path)
            if os.path.isfile(asset_path):
                return send_from_directory(static_folder, path)

        return send_from_directory(static_folder, 'index.html')
    
    if should_log_startup:
        if app.static_folder:
            logger.info(f"Serving frontend from: {app.static_folder}")
        logger.info("MiroFish Backend started successfully")
    
    return app
