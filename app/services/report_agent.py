"""
Report Agent Service — single-pass report generation from simulation data.
"""

import os
import json
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .graph_tools import GraphToolsService

logger = get_logger('mirofish.report_agent')


def _detect_language(text: str) -> str:
    if not text:
        return "en"
    cjk_count = 0
    total_count = 0
    for char in text:
        if not char.isspace():
            total_count += 1
            if "\u4e00" <= char <= "\u9fff" or "\u3400" <= char <= "\u4dbf":
                cjk_count += 1
    if total_count == 0:
        return "en"
    return "zh" if cjk_count / total_count > 0.05 else "en"


class ReportStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"title": self.title, "content": self.content}

    def to_markdown(self, level: int = 2) -> str:
        prefix = "#" * level
        md = f"{prefix} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    title: str
    summary: str
    sections: List[ReportSection]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections],
        }

    def to_markdown(self) -> str:
        md = f"# {self.title}\n\n> {self.summary}\n\n---\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


class ReportAgent:
    """Single-pass report generator from simulation data."""

    def __init__(
        self,
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        graph_tools: Optional[GraphToolsService] = None,
    ):
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        self.llm = llm_client or LLMClient()
        self.graph_tools = graph_tools or GraphToolsService()
        self.report_language = _detect_language(simulation_requirement)
        logger.info(f"ReportAgent initialized: graph_id={graph_id}, simulation_id={simulation_id}")

    def generate_report_fast(
        self,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None,
    ) -> Report:
        """Single-pass report generation — gathers all data upfront, one LLM call."""
        import uuid as _uuid

        if not report_id:
            report_id = f"report_{_uuid.uuid4().hex[:12]}"

        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat(),
        )

        try:
            ReportManager._ensure_report_folder(report_id)
            ReportManager.save_report(report)

            if progress_callback:
                progress_callback("generating", 10, "Gathering simulation data...")

            # Gather all data upfront
            context = self.graph_tools.get_simulation_context(
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement,
            )
            graph_stats = context.get("graph_statistics", {})
            related_facts = context.get("related_facts", [])

            all_nodes = self.graph_tools.get_all_nodes(self.graph_id)
            entity_summaries = []
            for node in all_nodes[:20]:
                summary = f"- {node.name} ({', '.join(node.labels)})"
                if node.summary:
                    summary += f": {node.summary}"
                entity_summaries.append(summary)

            from .simulation_runner import SimulationRunner
            timeline = SimulationRunner.get_timeline(self.simulation_id)
            agent_stats = SimulationRunner.get_agent_stats(self.simulation_id)
            actions = SimulationRunner.get_all_actions(self.simulation_id)

            # Sample up to 30 most interesting actions
            interesting_actions = [
                a for a in actions
                if a.action_type not in ("DO_NOTHING", "REFRESH", "TREND")
            ]
            interesting_actions.sort(key=lambda a: a.timestamp)
            action_summaries = []
            for a in interesting_actions[:30]:
                content_preview = (a.action_args.get("content") or a.result or "")[:200]
                action_summaries.append(
                    f"[Round {a.round_num}] [{a.platform}] {a.agent_name} ({a.action_type}): {content_preview}"
                )

            # Interview a panel of agents (size configurable; with activity
            # data the selector stratifies vocal / relevant / silent agents)
            interview_text = ""
            try:
                if agent_stats:
                    activity_by_agent = {
                        int(s["agent_id"]): int(s.get("total_actions", 0))
                        for s in agent_stats
                        if s.get("agent_id") is not None
                    }
                    interview_result = self.graph_tools.interview_agents(
                        simulation_id=self.simulation_id,
                        interview_requirement=f"What is your prediction for how {self.simulation_requirement}? What surprised you during the simulation?",
                        simulation_requirement=self.simulation_requirement,
                        max_agents=Config.INTERVIEW_MAX_AGENTS,
                        activity_by_agent=activity_by_agent,
                    )
                    if hasattr(interview_result, "to_text"):
                        interview_text = interview_result.to_text()
            except Exception as e:
                logger.warning(f"Interview failed (non-fatal): {e}")

            if progress_callback:
                progress_callback("generating", 40, "Generating report...")

            facts_text = "\n".join(
                f"- {f if isinstance(f, str) else f.get('fact', f.get('text', ''))}"
                for f in related_facts[:15]
            ) or "No facts extracted."
            entities_text = "\n".join(entity_summaries) or "No entities."
            actions_text = "\n".join(action_summaries) or "No notable actions."

            timeline_text = "\n".join(
                f"Round {t['round_num']}: {t['total_actions']} actions ({t['twitter_actions']} twitter, {t['reddit_actions']} reddit)"
                for t in timeline
            ) or "No timeline data."

            system_prompt = (
                "You are an expert analyst writing a prediction report based on a social media simulation.\n"
                "You are writing from a god's-eye view of a simulated future — not describing the present, but predicting what will happen.\n"
                "Write in English. Be analytical, specific, and evidence-based. Quote agent statements where relevant.\n"
                "Do NOT repeat the same data points across sections. Each section should cover distinct ground."
            )

            user_prompt = f"""## Simulation Requirement
{self.simulation_requirement}

## Knowledge Graph
Entities ({graph_stats.get('total_nodes', 0)} nodes, {graph_stats.get('total_edges', 0)} edges):
{entities_text}

Key facts:
{facts_text}

## Simulation Results
{timeline_text}

## Notable Agent Actions (simulated social media posts)
{actions_text}

## Agent Interviews
{interview_text or "No interviews available."}

---

Write a prediction report with:
1. A title and one-line executive summary
2. 3-4 analytical sections (use ## for section headers)
3. Each section should analyze a different dimension: key actors, policy dynamics, public discourse patterns, risks/opportunities
4. Quote specific agent actions and interview responses as evidence
5. Keep total length under 2000 words — be dense and analytical, not verbose"""

            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=4096,
            )

            if progress_callback:
                progress_callback("generating", 90, "Saving report...")

            # Parse title and summary from response
            lines = response.strip().split("\n")
            title = "Simulation Report"
            summary = ""
            for line in lines:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            for line in lines:
                if line.startswith("> "):
                    summary = line[2:].strip()
                    break

            outline = ReportOutline(
                title=title,
                summary=summary,
                sections=[ReportSection(title=title, content=response)],
            )

            report.outline = outline
            report.markdown_content = response
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()

            ReportManager.save_report(report)
            ReportManager.save_outline(report_id, outline)
            md_path = ReportManager._get_report_markdown_path(report_id)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(response)

            if progress_callback:
                progress_callback("generating", 100, "Report complete")

            logger.info(f"Single-pass report generated: {report_id}")
            return report

        except Exception as exc:
            report.status = ReportStatus.FAILED
            report.error = str(exc)
            report.completed_at = datetime.now().isoformat()
            try:
                ReportManager.save_report(report)
            except Exception:
                pass
            logger.error(f"Report generation failed: {exc}")
            raise


class ReportManager:
    """Report persistence storage and retrieval."""

    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')

    @classmethod
    def _ensure_reports_dir(cls):
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)

    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        return os.path.join(cls.REPORTS_DIR, report_id)

    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder

    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "meta.json")

    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")

    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "outline.json")

    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        cls._ensure_report_folder(report_id)
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def save_report(cls, report: Report) -> None:
        cls._ensure_report_folder(report.report_id)
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)

    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        path = cls._get_report_path(report_id)
        if not os.path.exists(path):
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = [
                ReportSection(title=s['title'], content=s.get('content', ''))
                for s in outline_data.get('sections', [])
            ]
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections,
            )

        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()

        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error'),
        )

    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        cls._ensure_reports_dir()
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        return None

    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        cls._ensure_reports_dir()
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            if os.path.isdir(item_path):
                report = cls.get_report(item)
            elif item.endswith('.json'):
                report = cls.get_report(item[:-5])
            else:
                continue
            if report and (simulation_id is None or report.simulation_id == simulation_id):
                reports.append(report)
        reports.sort(key=lambda r: r.created_at, reverse=True)
        return reports[:limit]

    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        import shutil
        folder_path = cls._get_report_folder(report_id)
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            return True
        deleted = False
        for ext in ('.json', '.md'):
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}{ext}")
            if os.path.exists(old_path):
                os.remove(old_path)
                deleted = True
        return deleted
