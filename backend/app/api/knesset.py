"""
KnessetSim API routes
Political simulation, MK chat, historical queries, and scenario planning
"""

import uuid
import threading
from contextlib import nullcontext
from flask import Blueprint, request, jsonify, current_app

from ..utils.logger import get_logger

logger = get_logger('mirofish.api.knesset')

knesset_bp = Blueprint('knesset', __name__, url_prefix='/api/knesset')

# In-memory store for running simulations
_simulations: dict = {}


def _run_simulation_background(sim_id: str, question_he: str, rounds: int, scenario: dict | None, app=None, platform: str = "plenum", social_layer: bool = True, modifiers: list | None = None):
    """Run simulation in background thread, updating _simulations store."""
    try:
        from ..services.knesset.orchestrator import KnessetOrchestrator
        from ..resources.llm.router import LLMRouter
        import os

        # Need app context for graph_storage
        ctx = app.app_context() if app else nullcontext()
        with ctx:
            graph_storage = app.extensions['graph_storage'] if app else None

            # Initialize LLM Router with Groq
            config_path = os.path.join(os.path.dirname(__file__), '../../config/llm_router.yaml')
            try:
                router = LLMRouter(config_path=config_path)
                logger.info(f"LLM Router initialized for simulation {sim_id}")
            except Exception as re:
                logger.warning(f"LLM Router init failed: {re}, using None")
                router = None

            orchestrator = KnessetOrchestrator(router=router, graph_storage=graph_storage)
            _simulations[sim_id]['status'] = 'running'

            import asyncio
            result = asyncio.run(orchestrator.run_simulation(
                question_he=question_he,
                rounds=rounds,
                scenario=scenario,
                platform=platform,
            ))

            # Extract actions from rounds_data
            all_actions = []
            for rd in result.get('rounds_data', []):
                all_actions.extend(rd.get('actions', []))

            _simulations[sim_id].update({
                'status': 'completed',
                'current_round': rounds,
                'actions': all_actions,
                'report': result.get('summary'),
                'bill_outcomes': result.get('bill_outcomes', {}),
                'rounds_data': result.get('rounds_data', []),
            })
    except Exception as e:
        logger.error(f"Simulation {sim_id} failed: {e}")
        _simulations[sim_id].update({
            'status': 'failed',
            'error': str(e),
        })


def _run_scenario_background(sim_id: str, scenario_type: str, params: dict):
    """Run scenario simulation in background thread."""
    try:
        from ..services.knesset.orchestrator import KnessetOrchestrator
        orchestrator = KnessetOrchestrator()
        _simulations[sim_id]['status'] = 'running'

        result = orchestrator.run_scenario(
            scenario_type=scenario_type,
            params=params,
            progress_callback=lambda r: _simulations[sim_id].update({'current_round': r})
        )

        _simulations[sim_id].update({
            'status': 'completed',
            'actions': result.get('actions', []),
            'report': result.get('report'),
        })
    except Exception as e:
        logger.error(f"Scenario simulation {sim_id} failed: {e}")
        _simulations[sim_id].update({
            'status': 'failed',
            'error': str(e),
        })


# ============== Simulation Endpoints ==============

@knesset_bp.route('/simulate', methods=['POST'])
def simulate():
    """
    Launch a political simulation.

    Body: { "question_he": str, "rounds": int(5), "scenario": optional dict }
    Returns simulation_id for polling.
    """
    try:
        data = request.get_json(force=True)
        question_he = data.get('question_he')
        if not question_he:
            return jsonify({"success": False, "error": "question_he is required"}), 400

        rounds = data.get('rounds', 5)
        scenario = data.get('scenario')
        platform = data.get('platform', 'plenum')
        social_layer = data.get('social_layer', True)
        modifiers = data.get('modifiers', [])

        sim_id = str(uuid.uuid4())
        _simulations[sim_id] = {
            'status': 'queued',
            'current_round': 0,
            'total_rounds': rounds,
            'actions': [],
            'report': None,
        }

        app = current_app._get_current_object()
        thread = threading.Thread(
            target=_run_simulation_background,
            args=(sim_id, question_he, rounds, scenario, app, platform, social_layer, modifiers),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": sim_id,
                "status": "running",
            }
        })

    except Exception as e:
        logger.error(f"Failed to start simulation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@knesset_bp.route('/simulate/<simulation_id>', methods=['GET'])
def get_simulation(simulation_id: str):
    """Get simulation status and results."""
    try:
        sim = _simulations.get(simulation_id)
        if not sim:
            return jsonify({"success": False, "error": "Simulation not found"}), 404

        return jsonify({
            "success": True,
            "data": {
                "status": sim['status'],
                "current_round": sim.get('current_round', 0),
                "total_rounds": sim.get('total_rounds', 0),
                "actions": sim.get('actions', []),
                "report": sim.get('report'),
                "error": sim.get('error'),
            }
        })

    except Exception as e:
        logger.error(f"Failed to get simulation {simulation_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Historical Query ==============

@knesset_bp.route('/query', methods=['POST'])
def query():
    """
    Historical query against Knesset data.

    Body: { "question_he": str }
    """
    try:
        data = request.get_json(force=True)
        question_he = data.get('question_he')
        if not question_he:
            return jsonify({"success": False, "error": "question_he is required"}), 400

        from ..services.knesset.historical_query import KnessetHistoricalQuery
        hq = KnessetHistoricalQuery()
        result = hq.query(question_he)

        return jsonify({
            "success": True,
            "data": {
                "similar_bills": result.get('similar_bills', []),
                "analysis_he": result.get('analysis_he', ''),
            }
        })

    except Exception as e:
        logger.error(f"Historical query failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== MK Endpoints ==============

@knesset_bp.route('/mks', methods=['GET'])
def list_mks():
    """
    List MKs from the political graph.

    Query params: ?faction=&current_only=true
    """
    try:
        faction = request.args.get('faction')
        current_only = request.args.get('current_only', 'true').lower() == 'true'

        from ..services.knesset.knesset_graph import KnessetGraph
        from flask import current_app
        graph = KnessetGraph(current_app.extensions['graph_storage'])
        mks = graph.get_all_mks(current_only=current_only)

        attrs_key = 'attributes'
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": mk.get('id', ''),
                    "name_he": mk.get('name', ''),
                    "faction": mk.get(attrs_key, {}).get('party', ''),
                    "influence_score": mk.get(attrs_key, {}).get('influence_score', 0),
                    "is_current_mk": mk.get(attrs_key, {}).get('is_current_mk', False),
                }
                for mk in mks
            ]
        })

    except Exception as e:
        logger.error(f"Failed to list MKs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@knesset_bp.route('/mks/<mk_id>', methods=['GET'])
def get_mk(mk_id: str):
    """Full MK detail with persona and memory."""
    try:
        from ..services.knesset.knesset_graph import KnessetGraph
        from flask import current_app
        graph = KnessetGraph(current_app.extensions['graph_storage'])
        mk = graph.get_mk(mk_id)
        if not mk:
            return jsonify({"success": False, "error": "MK not found"}), 404

        return jsonify({
            "success": True,
            "data": {
                "persona": mk.get('persona'),
                "voting_patterns": mk.get('voting_patterns'),
                "memory_summary": mk.get('memory_summary'),
            }
        })

    except Exception as e:
        logger.error(f"Failed to get MK {mk_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Chat ==============

@knesset_bp.route('/chat', methods=['POST'])
def chat():
    """
    Chat with one or more MKs.

    Body: { "mk_ids": [str], "message_he": str, "context": optional dict }
    Single MK = direct chat, multiple = group discussion.
    """
    try:
        data = request.get_json(force=True)
        mk_ids = data.get('mk_ids', [])
        message_he = data.get('message_he')
        context = data.get('context')

        if not mk_ids:
            return jsonify({"success": False, "error": "mk_ids is required"}), 400
        if not message_he:
            return jsonify({"success": False, "error": "message_he is required"}), 400

        from ..services.knesset.chat_interface import KnessetChat
        chat_service = KnessetChat()

        if len(mk_ids) == 1:
            responses = [chat_service.chat_single(mk_ids[0], message_he, context=context)]
        else:
            responses = chat_service.chat_group(mk_ids, message_he, context=context)

        return jsonify({
            "success": True,
            "data": {
                "responses": [
                    {
                        "mk_id": r['mk_id'],
                        "mk_name": r['mk_name'],
                        "response_he": r['response_he'],
                    }
                    for r in responses
                ]
            }
        })

    except Exception as e:
        logger.error(f"Chat failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Factions ==============

@knesset_bp.route('/factions', methods=['GET'])
def list_factions():
    """List factions with coalition status."""
    try:
        from ..services.knesset.knesset_graph import KnessetGraph
        from flask import current_app
        graph = KnessetGraph(current_app.extensions['graph_storage'])
        faction_nodes = graph.storage.list_nodes(label="Faction")
        coalition_factions = graph.get_coalition_factions()
        result = []
        for f in faction_nodes:
            attrs = f.get('attributes', {})
            result.append({
                "id": f.get('id', ''),
                "name_he": f.get('name', ''),
                "coalition": f.get('name', '') in coalition_factions,
                "seats": attrs.get('seats', 0),
                "is_current": attrs.get('is_current', False),
            })
        return jsonify({"success": True, "data": result})

    except Exception as e:
        logger.error(f"Failed to list factions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Bills ==============

@knesset_bp.route('/bills', methods=['GET'])
def list_bills():
    """
    List bills from the graph.

    Query params: ?search=&status=&limit=20
    """
    try:
        search = request.args.get('search')
        status = request.args.get('status')
        limit = request.args.get('limit', 20, type=int)

        from ..services.knesset.knesset_graph import KnessetGraph
        from flask import current_app
        graph = KnessetGraph(current_app.extensions['graph_storage'])
        bills = graph.get_bills(search=search, status=status, limit=limit)

        return jsonify({
            "success": True,
            "data": [
                {
                    "id": b['id'],
                    "name_he": b['name_he'],
                    "status": b.get('status'),
                    "sponsor": b.get('sponsor'),
                }
                for b in bills
            ]
        })

    except Exception as e:
        logger.error(f"Failed to list bills: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Scenario ==============

@knesset_bp.route('/scenario', methods=['POST'])
def run_scenario():
    """
    Run a what-if scenario simulation.

    Body: { "type": "election_change"|"defection"|"crisis"|"coalition_collapse", "params": dict }
    """
    try:
        data = request.get_json(force=True)
        scenario_type = data.get('type')
        params = data.get('params', {})

        valid_types = {'election_change', 'defection', 'crisis', 'coalition_collapse'}
        if scenario_type not in valid_types:
            return jsonify({
                "success": False,
                "error": f"Invalid scenario type. Must be one of: {', '.join(sorted(valid_types))}"
            }), 400

        sim_id = str(uuid.uuid4())
        _simulations[sim_id] = {
            'status': 'queued',
            'current_round': 0,
            'total_rounds': 0,
            'actions': [],
            'report': None,
        }

        thread = threading.Thread(
            target=_run_scenario_background,
            args=(sim_id, scenario_type, params),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": sim_id,
                "status": "running",
            }
        })

    except Exception as e:
        logger.error(f"Failed to start scenario: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Stats ==============

@knesset_bp.route('/stats', methods=['GET'])
def get_stats():
    """Dashboard stats."""
    try:
        from ..services.knesset.knesset_graph import KnessetGraph
        from flask import current_app
        graph = KnessetGraph(current_app.extensions['graph_storage'])
        stats = graph.get_stats()

        return jsonify({
            "success": True,
            "data": {
                "mks_count": stats.get('mks_count', 0),
                "factions_count": stats.get('factions_count', 0),
                "bills_count": stats.get('bills_count', 0),
                "simulations_run": len(_simulations),
            }
        })

    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Live Data Injection ==============

@knesset_bp.route('/inject', methods=['POST'])
def inject_event():
    """
    Inject a breaking news event into a running simulation.

    Body: {
        "simulation_id": str,
        "event_he": str (Hebrew text of the event),
        "source": str (optional, e.g. "twitter", "telegram", "manual")
    }
    """
    try:
        data = request.get_json(force=True)
        sim_id = data.get('simulation_id')
        event_he = data.get('event_he')

        if not sim_id or not event_he:
            return jsonify({
                "success": False,
                "error": "simulation_id and event_he are required"
            }), 400

        sim = _simulations.get(sim_id)
        if not sim:
            return jsonify({"success": False, "error": "Simulation not found"}), 404

        if sim.get('status') != 'running':
            return jsonify({
                "success": False,
                "error": f"Simulation is {sim.get('status')}, not running"
            }), 400

        # Store injected event for the simulation's injector to pick up
        source = data.get('source', 'manual')
        if 'injected_events' not in sim:
            sim['injected_events'] = []
        sim['injected_events'].append({
            "event_he": event_he,
            "source": source,
            "injected_at": __import__('datetime').datetime.now(
                __import__('datetime').timezone.utc
            ).isoformat(),
        })

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": sim_id,
                "events_injected": len(sim['injected_events']),
            }
        })

    except Exception as e:
        logger.error(f"Failed to inject event: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Platforms List ==============

@knesset_bp.route('/platforms', methods=['GET'])
def list_platforms():
    """List available simulation platforms."""
    return jsonify({
        "success": True,
        "data": [
            {
                "id": "plenum",
                "name_he": "מליאת הכנסת",
                "description_he": "דיון פרלמנטרי מלא עם הצבעות, נאומים והצעות חוק",
                "actions": ["PROPOSE_BILL", "VOTE", "SPEAK_IN_PLENUM", "LOBBY",
                           "FORM_ALLIANCE", "DEFECT", "AMEND_BILL", "DO_NOTHING"],
            },
            {
                "id": "roundtable",
                "name_he": "שולחן עגול",
                "description_he": "דיון פתוח עם סדר דוברים, כל אחד מדבר בתורו",
                "actions": ["SPEAK", "RESPOND", "CHALLENGE", "AGREE", "PROPOSE", "ABSTAIN"],
            },
            {
                "id": "negotiation",
                "name_he": "משא ומתן",
                "description_he": "משא ומתן מובנה עם הצעות, הצעות נגדיות ובלופים",
                "actions": ["OFFER", "COUNTER", "CONCEDE", "BLUFF", "WALK_AWAY", "ACCEPT"],
            },
            {
                "id": "brainstorm",
                "name_he": "סיעור מוחות",
                "description_he": "חשיבה יצירתית בשני שלבים: רעיונות חופשיים ואז סינון",
                "actions": ["IDEA", "BUILD_ON", "CRITIQUE", "COMBINE", "PRIORITIZE", "VOTE"],
            },
            {
                "id": "decision",
                "name_he": "קבלת החלטות",
                "description_he": "תהליך מובנה: ניתוח → טיעון → הצבעה",
                "actions": ["ANALYZE", "ADVOCATE", "DEVIL_ADVOCATE", "VOTE", "ABSTAIN", "DEFER"],
            },
            {
                "id": "press_conference",
                "name_he": "מסיבת עיתונאים",
                "description_he": "ח\"כים מול עיתונאים — שאלות, תשובות, אתגורים",
                "actions": ["ASK", "ANSWER", "FOLLOW_UP", "DEFLECT", "NO_COMMENT", "CHALLENGE"],
            },
        ]
    })


# ============== Claude Analysis Chat ==============

_claude_sessions: dict = {}  # session_id -> {history: [], state: {}}


@knesset_bp.route('/claude/chat', methods=['POST'])
def claude_chat():
    """
    Chat with Claude about simulation state and political analysis.

    Body: {
        "message_he": str,
        "simulation_id": str | null,
        "session_id": str | null (reuse existing session),
        "simulation_state": dict | null (direct state override)
    }
    """
    try:
        data = request.get_json(force=True)
        message_he = data.get('message_he')
        if not message_he:
            return jsonify({"success": False, "error": "message_he is required"}), 400

        sim_id = data.get('simulation_id')
        session_id = data.get('session_id') or str(uuid.uuid4())
        sim_state = data.get('simulation_state') or {}

        # Get simulation state if sim_id provided
        if sim_id and sim_id in _simulations:
            sim_state = _simulations[sim_id]

        # Get or create session
        if session_id not in _claude_sessions:
            _claude_sessions[session_id] = {"history": [], "state": sim_state}

        session = _claude_sessions[session_id]
        session["state"] = sim_state  # Always update state

        # Build context prompt
        state_summary = ""
        if sim_state:
            state_summary = f"""
מצב סימולציה נוכחי:
- סטטוס: {sim_state.get('status', 'unknown')}
- סבב: {sim_state.get('current_round', '?')}/{sim_state.get('total_rounds', '?')}
- פעולות אחרונות: {len(sim_state.get('actions', []))} פעולות
"""

        system_prompt = f"""אתה מנתח פוליטי מומחה של הכנסת הישראלית. אתה מנתח סימולציות פוליטיות ונותן תובנות חדות.
ענה תמיד בעברית. היה תמציתי וברור.
החזר JSON בפורמט: {{"text": "הניתוח שלך", "mks": [{{"id": "...", "name": "...", "faction": "..."}}], "voteTally": {{"for": 0, "against": 0, "abstain": 0}}, "bills": [{{"id": "...", "title": "..."}}]}}
אם אין נתונים רלוונטיים לmks/voteTally/bills, החזר מערכים/אובייקטים ריקים.
{state_summary}"""

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(session["history"][-10:])  # Last 10 messages for context
        messages.append({"role": "user", "content": message_he})

        # Call LLM via existing provider
        from ..utils.llm_client import LLMClient
        client = LLMClient()

        try:
            response = client.chat_json(messages=messages, max_tokens=2000, task_type="claude_chat")
        except Exception:
            # Fallback to text response
            response_text = client.chat(messages=messages, max_tokens=2000)
            response = {"text": response_text, "mks": [], "voteTally": {}, "bills": []}

        # Save to history
        session["history"].append({"role": "user", "content": message_he})
        session["history"].append({"role": "assistant", "content": response.get("text", str(response))})

        return jsonify({
            "success": True,
            "data": {
                "session_id": session_id,
                "text": response.get("text", ""),
                "mks": response.get("mks", []),
                "voteTally": response.get("voteTally", {}),
                "bills": response.get("bills", []),
            }
        })

    except Exception as e:
        logger.error(f"Claude chat failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Profile Cache ==============

@knesset_bp.route('/profiles/warm', methods=['POST'])
def warm_profiles_cache():
    """Pre-generate and cache all agent profiles for a graph."""
    try:
        data = request.get_json(force=True)
        graph_id = data.get('graph_id')

        from ..services.oasis_profile_generator import OasisProfileGenerator
        from ..services.entity_reader import EntityReader

        storage = current_app.extensions.get('graph_storage')
        generator = OasisProfileGenerator(graph_id=graph_id, storage=storage)

        reader = EntityReader(storage=storage, graph_id=graph_id)
        entities = reader.get_all_entities()

        result = generator.warm_cache(entities)

        return jsonify({"success": True, "data": result})

    except Exception as e:
        logger.error(f"Profile cache warm failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@knesset_bp.route('/profiles/invalidate', methods=['POST'])
def invalidate_profiles_cache():
    """Invalidate cached profiles."""
    try:
        data = request.get_json(force=True) if request.data else {}
        entity_uuid = data.get('entity_uuid')

        from ..services.oasis_profile_generator import OasisProfileGenerator
        generator = OasisProfileGenerator()
        deleted = generator.invalidate_cache(entity_uuid=entity_uuid)

        return jsonify({"success": True, "data": {"deleted": deleted}})

    except Exception as e:
        logger.error(f"Profile cache invalidation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== Live Data Feed ==============

_live_feed_instance = None


def _get_live_feed():
    """Get or create singleton LiveDataFeed instance."""
    global _live_feed_instance
    if _live_feed_instance is None:
        from ..services.knesset.live_data_feed import LiveDataFeed
        _live_feed_instance = LiveDataFeed()
        _live_feed_instance.setup_default_feeds()
    return _live_feed_instance


@knesset_bp.route('/live-feed/inject', methods=['POST'])
def inject_live_event():
    """Manually inject a political event into the live feed."""
    try:
        data = request.get_json(force=True)
        title_he = data.get('title_he')
        content_he = data.get('content_he', '')
        event_type = data.get('event_type', 'manual')
        impact = data.get('impact', 'high')

        if not title_he:
            return jsonify({"success": False, "error": "title_he is required"}), 400

        from ..services.knesset.live_data_feed import KnessetEvent
        from datetime import datetime

        event = KnessetEvent(
            event_id=str(uuid.uuid4()),
            title_he=title_he,
            content_he=content_he,
            event_type=event_type,
            source="manual",
            timestamp=datetime.now().isoformat(),
            impact=impact,
        )

        feed = _get_live_feed()
        feed.inject_event(event)

        return jsonify({
            "success": True,
            "data": {"event_id": event.event_id, "title": title_he}
        })

    except Exception as e:
        logger.error(f"Live feed injection failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@knesset_bp.route('/live-feed/events', methods=['GET'])
def get_live_feed_events():
    """Get recent live feed events."""
    try:
        limit = request.args.get('limit', 20, type=int)
        feed = _get_live_feed()
        events = feed.get_recent_events(limit=limit) if hasattr(feed, 'get_recent_events') else []

        return jsonify({
            "success": True,
            "data": [
                {
                    "event_id": e.event_id if hasattr(e, 'event_id') else str(e),
                    "title": e.title if hasattr(e, 'title') else str(e),
                    "event_type": e.event_type if hasattr(e, 'event_type') else 'unknown',
                    "timestamp": e.timestamp if hasattr(e, 'timestamp') else '',
                }
                for e in events
            ]
        })

    except Exception as e:
        logger.error(f"Live feed events failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
