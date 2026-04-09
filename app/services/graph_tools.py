"""
Graph retrieval tools service.
Provides graph queries and agent interview capabilities for report generation.
"""

import json
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from .graph_db import GraphDatabase
from .graph_storage import GraphStorage

from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient

logger = get_logger('mirofish.graph_tools')


@dataclass
class NodeInfo:
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
        }

    def to_text(self) -> str:
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "Unknown type")
        return f"Entity: {self.name} (Type: {entity_type})\nSummary: {self.summary}"


@dataclass
class EdgeInfo:
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at,
        }

    def to_text(self, include_temporal: bool = False) -> str:
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"Relationship: {source} --[{self.name}]--> {target}\nFact: {self.fact}"
        if include_temporal:
            base_text += f"\nValidity: {self.valid_at or 'Unknown'} - {self.invalid_at or 'Present'}"
            if self.expired_at:
                base_text += f" (Expired: {self.expired_at})"
        return base_text


@dataclass
class AgentInterview:
    agent_name: str
    agent_role: str
    agent_bio: str
    question: str
    response: str
    key_quotes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes,
        }

    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        text += f"_Bio: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**Key Quotes:**\n"
            for quote in self.key_quotes:
                clean = quote.strip().strip('\u201c\u201d"\u300c\u300d')
                if clean and len(clean) >= 10:
                    if len(clean) > 150:
                        clean = clean[:147] + "..."
                    text += f'> "{clean}"\n'
        return text


@dataclass
class InterviewResult:
    interview_topic: str
    interview_questions: List[str]
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    interviews: List[AgentInterview] = field(default_factory=list)
    selection_reasoning: str = ""
    summary: str = ""
    total_agents: int = 0
    interviewed_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count,
        }

    def to_text(self) -> str:
        text_parts = [
            "## In-Depth Interview Report",
            f"**Interview Topic:** {self.interview_topic}",
            f"**Interviewees:** {self.interviewed_count} / {self.total_agents} simulated agents",
            "\n### Interviewee Selection Reasoning",
            self.selection_reasoning or "(Automatically selected)",
            "\n---",
            "\n### Interview Transcripts",
        ]
        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### Interview #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("(No interview records)\n\n---")
        text_parts.append("\n### Interview Summary and Key Insights")
        text_parts.append(self.summary or "(No summary)")
        return "\n".join(text_parts)


class GraphToolsService:
    """Graph retrieval tools for report generation and agent interviews."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        storage: Optional[GraphStorage] = None,
    ):
        self.db = GraphDatabase()
        self.storage = storage
        self._llm_client = llm_client

    @property
    def llm(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def _node_value(self, node: Any, attr: str, key: str, default: Any = "") -> Any:
        if hasattr(node, attr):
            return getattr(node, attr)
        return node.get(key, default)

    def _node_labels(self, node: Any) -> List[str]:
        if hasattr(node, "labels"):
            return node.labels or []
        label = node.get("label", "Entity")
        return ["Entity"] if label == "Entity" else ["Entity", label]

    def _edge_value(self, edge: Any, attr: str, key: str, default: Any = "") -> Any:
        if hasattr(edge, attr):
            return getattr(edge, attr)
        return edge.get(key, default)

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        if self.storage is not None:
            nodes = self.storage.list_nodes()
        else:
            nodes = self.db.get_all_nodes(graph_id)

        result = []
        for node in nodes:
            result.append(NodeInfo(
                uuid=self._node_value(node, "uuid_", "id") or "",
                name=self._node_value(node, "name", "name") or "",
                labels=self._node_labels(node),
                summary=self._node_value(node, "summary", "summary") or "",
                attributes=self._node_value(node, "attributes", "attributes", {}) or {},
            ))
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        if self.storage is not None:
            edges = self.storage.get_edges()
        else:
            edges = self.db.get_all_edges(graph_id)

        result = []
        for edge in edges:
            edge_info = EdgeInfo(
                uuid=self._edge_value(edge, "uuid_", "id") or "",
                name=self._edge_value(edge, "name", "relation") or "",
                fact=self._edge_value(edge, "fact", "fact") or "",
                source_node_uuid=self._edge_value(edge, "source_node_uuid", "source_id") or "",
                target_node_uuid=self._edge_value(edge, "target_node_uuid", "target_id") or "",
            )
            if include_temporal:
                edge_info.created_at = self._edge_value(edge, "created_at", "created_at", None)
                edge_info.valid_at = self._edge_value(edge, "valid_at", "valid_at", None)
                edge_info.invalid_at = self._edge_value(edge, "invalid_at", "invalid_at", None)
                edge_info.expired_at = self._edge_value(edge, "expired_at", "expired_at", None)
            result.append(edge_info)
        return result

    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)

        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1

        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1

        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types,
        }

    def get_simulation_context(
        self,
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30,
    ) -> Dict[str, Any]:
        """Get simulation-related context: stats, entities, and edge facts."""
        stats = self.get_graph_statistics(graph_id)
        all_nodes = self.get_all_nodes(graph_id)
        all_edges = self.get_all_edges(graph_id)

        # Collect edge facts as related facts
        related_facts = [e.fact for e in all_edges if e.fact][:limit]

        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node.name,
                    "type": custom_labels[0],
                    "summary": node.summary,
                })

        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": related_facts,
            "graph_statistics": stats,
            "entities": entities[:limit],
            "total_entities": len(entities),
        }

    # ========== Agent Interview ==========

    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None,
    ) -> InterviewResult:
        """Interview simulated agents via OASIS IPC."""
        from .simulation_runner import SimulationRunner

        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or [],
        )

        profiles = self._load_agent_profiles(simulation_id)
        if not profiles:
            result.summary = "No agent profile files found for interview"
            return result

        result.total_agents = len(profiles)

        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents,
        )
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning

        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents,
            )

        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        optimized_prompt = (
            "You are being interviewed. Please draw on your persona, all past memories, and actions "
            "to answer the following questions directly in plain text.\n"
            "Response requirements:\n"
            "1. Answer directly in natural language; do not call any tools\n"
            "2. Do not return JSON format or tool call format\n"
            "3. Do not use Markdown headings (such as #, ##, ###)\n"
            "4. Answer each question in order, starting each answer with 'Question X:'\n"
            "5. Separate answers to each question with a blank line\n"
            "6. Provide substantive answers, with at least 2-3 sentences per question\n\n"
            f"{combined_prompt}"
        )

        try:
            interviews_request = [
                {"agent_id": idx, "prompt": optimized_prompt}
                for idx in selected_indices
            ]

            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,
                timeout=180.0,
            )

            if not api_result.get("success", False):
                result.summary = f"Interview API call failed: {api_result.get('error', 'Unknown error')}"
                return result

            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}

            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "Unknown")
                agent_bio = agent.get("bio", "")

                twitter_response = self._clean_tool_call_response(
                    results_dict.get(f"twitter_{agent_idx}", {}).get("response", "")
                )
                reddit_response = self._clean_tool_call_response(
                    results_dict.get(f"reddit_{agent_idx}", {}).get("response", "")
                )

                twitter_text = twitter_response or "(No response from this platform)"
                reddit_text = reddit_response or "(No response from this platform)"
                response_text = f"[Twitter Platform Response]\n{twitter_text}\n\n[Reddit Platform Response]\n{reddit_text}"

                # Extract key quotes
                combined = f"{twitter_response} {reddit_response}"
                clean_text = re.sub(r'#{1,6}\s+', '', combined)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'(?:Question)\s*\d+[：:]\s*', '', clean_text)

                sentences = re.split(r'[。！？.!?]', clean_text)
                meaningful = sorted(
                    [s.strip() for s in sentences if 20 <= len(s.strip()) <= 150],
                    key=len, reverse=True,
                )
                key_quotes = [s + "." for s in meaningful[:3]]

                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5],
                )
                result.interviews.append(interview)

            result.interviewed_count = len(result.interviews)

        except ValueError as e:
            result.summary = f"Interview failed: {e}. The simulation environment may have been shut down."
            return result
        except Exception as e:
            logger.error(f"Interview API call exception: {e}")
            result.summary = f"An error occurred during the interview: {e}"
            return result

        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement,
            )

        return result

    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        import os
        import csv

        sim_dir = os.path.join(os.path.dirname(__file__), f'../../uploads/simulations/{simulation_id}')

        reddit_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_path):
            try:
                with open(reddit_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read reddit_profiles.json: {e}")

        twitter_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_path):
            try:
                with open(twitter_path, 'r', encoding='utf-8') as f:
                    return [
                        {
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "Unknown",
                        }
                        for row in csv.DictReader(f)
                    ]
            except Exception as e:
                logger.warning(f"Failed to read twitter_profiles.csv: {e}")

        return []

    def _select_agents_for_interview(self, profiles, interview_requirement, simulation_requirement, max_agents):
        agent_summaries = [
            {
                "index": i,
                "name": p.get("realname", p.get("username", f"Agent_{i}")),
                "profession": p.get("profession", "Unknown"),
                "bio": p.get("bio", "")[:200],
                "interested_topics": p.get("interested_topics", []),
            }
            for i, p in enumerate(profiles)
        ]

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": (
                        "You are a professional interview planning expert. Select the most suitable interview subjects.\n"
                        "Criteria: relevance to topic, unique perspectives, diverse viewpoints.\n"
                        'Return JSON: {"selected_indices": [int], "reasoning": "string"}'
                    )},
                    {"role": "user", "content": (
                        f"Interview requirement: {interview_requirement}\n"
                        f"Background: {simulation_requirement or 'Not provided'}\n"
                        f"Agents ({len(agent_summaries)} total):\n{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}\n"
                        f"Select up to {max_agents} agents."
                    )},
                ],
                temperature=0.3,
            )
            indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "Selected based on relevance")
            agents = [profiles[i] for i in indices if 0 <= i < len(profiles)]
            valid_indices = [i for i in indices if 0 <= i < len(profiles)]
            return agents, valid_indices, reasoning
        except Exception as e:
            logger.warning(f"LLM agent selection failed: {e}")
            n = min(max_agents, len(profiles))
            return profiles[:n], list(range(n)), "Default selection"

    def _generate_interview_questions(self, interview_requirement, simulation_requirement, selected_agents):
        agent_roles = [a.get("profession", "Unknown") for a in selected_agents]
        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": (
                        "Generate 3-5 open-ended interview questions. Concise, under 50 words each.\n"
                        'Return JSON: {"questions": ["q1", "q2", ...]}'
                    )},
                    {"role": "user", "content": (
                        f"Topic: {interview_requirement}\n"
                        f"Background: {simulation_requirement or 'Not provided'}\n"
                        f"Interviewee roles: {', '.join(agent_roles)}"
                    )},
                ],
                temperature=0.5,
            )
            return response.get("questions", [f"What are your thoughts on {interview_requirement}?"])
        except Exception:
            return [
                f"What is your perspective on {interview_requirement}?",
                "What impact does this have on you or the group you represent?",
                "How do you think this issue should be resolved or improved?",
            ]

    def _generate_interview_summary(self, interviews, interview_requirement):
        if not interviews:
            return "No interviews were completed"
        interview_texts = [
            f"[{i.agent_name} ({i.agent_role})]\n{i.response[:500]}"
            for i in interviews
        ]
        try:
            return self.llm.chat(
                messages=[
                    {"role": "system", "content": (
                        "Summarize interview responses. Distill main viewpoints, identify consensus/disagreement, "
                        "highlight valuable quotes. Stay objective. Under 1000 words. Plain text, no markdown headings."
                    )},
                    {"role": "user", "content": (
                        f"Topic: {interview_requirement}\n\nInterviews:\n{''.join(interview_texts)}"
                    )},
                ],
                temperature=0.3,
                max_tokens=800,
            )
        except Exception as e:
            logger.warning(f"Failed to generate interview summary: {e}")
            return f"Interviewed {len(interviews)} agents: " + ", ".join(i.agent_name for i in interviews)


KuzuToolsService = GraphToolsService
