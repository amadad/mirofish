#!/bin/bash
set -e

mkdir -p /app/backend/uploads /app/backend/data

cd /app/backend

cat >/tmp/mirofish_runtime_app.py <<'PY'
import builtins
import importlib
import os
import secrets
import sys
import types

from flask import jsonify

sys.path.insert(0, '/app/backend')


def _get_bool_env(name, default=False):
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    return value.lower() in {'1', 'true', 'yes', 'on'}


def _get_cors_origins():
    raw = os.environ.get('CORS_ORIGINS', '')
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(',') if origin.strip()]


builtins._get_bool_env = _get_bool_env
builtins._get_cors_origins = _get_cors_origins
builtins.secrets = secrets

if os.environ.get('KUZU_DB_PATH') and not os.environ.get('GRAPH_DB_PATH'):
    os.environ['GRAPH_DB_PATH'] = os.environ['KUZU_DB_PATH']

base = '/app/backend/app'

for package_name in ['services', 'core', 'models', 'tools']:
    module = types.ModuleType(f'app.{package_name}')
    module.__path__ = [os.path.join(base, package_name)]
    sys.modules[f'app.{package_name}'] = module

tool_exports = {
    'app.tools.build_graph': ['BuildGraphTool'],
    'app.tools.generate_ontology': ['GenerateOntologyTool'],
    'app.tools.generate_report': ['GenerateReportTool'],
    'app.tools.prepare_simulation': ['PrepareSimulationTool'],
    'app.tools.run_simulation': ['RunSimulationTool'],
}

for module_name, export_names in tool_exports.items():
    tool_module = importlib.import_module(module_name)
    tool_package = sys.modules['app.tools']
    for export_name in export_names:
        setattr(tool_package, export_name, getattr(tool_module, export_name))

from app import create_app as _create_app


def create_app():
    app = _create_app()

    @app.get('/api/graph/nodes')
    def graph_nodes_compat():
        return jsonify([])

    return app
PY

echo "Starting gunicorn on 127.0.0.1:5001"
# Keep a single worker because SimulationRunner stores subprocess handles in class-level state.
PYTHONPATH="/tmp:/app/backend" uv run gunicorn -w 1 -b 127.0.0.1:5001 "mirofish_runtime_app:create_app()" &

echo "Starting nginx on 0.0.0.0:3000"
exec nginx -g "daemon off;"
