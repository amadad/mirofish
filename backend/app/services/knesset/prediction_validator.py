"""PredictionValidator — tracks simulation predictions, validates against
real outcomes, and calibrates future accuracy.

Stores predictions as JSON files in backend/data/knesset/predictions/.
Provides calibration stats and Hebrew prompt modifiers to improve LLM accuracy.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mirofish.knesset.prediction_validator")

# Default storage path relative to backend root
_DEFAULT_STORAGE = os.path.join(
    os.path.dirname(__file__), "../../../data/knesset/predictions"
)


# ---------------------------------------------------------------------------
# Prediction dataclass
# ---------------------------------------------------------------------------

@dataclass
class Prediction:
    """A single simulation prediction with optional validation fields."""

    prediction_id: str
    simulation_id: str
    created_at: str  # ISO timestamp
    question_he: str
    predicted_outcome: str  # "passed" / "failed" / custom
    predicted_votes_for: int
    predicted_votes_against: int
    predicted_swing_mks: List[str]
    confidence: float  # 0-1

    # Validation fields (filled later)
    actual_outcome: Optional[str] = None
    actual_votes_for: Optional[int] = None
    actual_votes_against: Optional[int] = None
    validated_at: Optional[str] = None
    accuracy_score: Optional[float] = None  # 0-1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Prediction:
        return cls(
            prediction_id=data["prediction_id"],
            simulation_id=data["simulation_id"],
            created_at=data["created_at"],
            question_he=data["question_he"],
            predicted_outcome=data["predicted_outcome"],
            predicted_votes_for=data["predicted_votes_for"],
            predicted_votes_against=data["predicted_votes_against"],
            predicted_swing_mks=data.get("predicted_swing_mks", []),
            confidence=data.get("confidence", 0.5),
            actual_outcome=data.get("actual_outcome"),
            actual_votes_for=data.get("actual_votes_for"),
            actual_votes_against=data.get("actual_votes_against"),
            validated_at=data.get("validated_at"),
            accuracy_score=data.get("accuracy_score"),
        )


# ---------------------------------------------------------------------------
# PredictionValidator
# ---------------------------------------------------------------------------

class PredictionValidator:
    """Tracks predictions, compares to real outcomes, calibrates accuracy."""

    def __init__(self, storage_dir: Optional[str] = None) -> None:
        self.storage_dir = storage_dir or _DEFAULT_STORAGE
        os.makedirs(self.storage_dir, exist_ok=True)
        self._cache: Dict[str, Prediction] = {}
        self._load_all()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _prediction_path(self, prediction_id: str) -> str:
        return os.path.join(self.storage_dir, f"{prediction_id}.json")

    def _save(self, prediction: Prediction) -> None:
        path = self._prediction_path(prediction.prediction_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prediction.to_dict(), f, ensure_ascii=False, indent=2)
        self._cache[prediction.prediction_id] = prediction

    def _load_all(self) -> None:
        self._cache.clear()
        if not os.path.isdir(self.storage_dir):
            return
        for fname in os.listdir(self.storage_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.storage_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                pred = Prediction.from_dict(data)
                self._cache[pred.prediction_id] = pred
            except Exception as exc:
                logger.warning("Failed to load prediction %s: %s", fname, exc)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_prediction(self, simulation_result: dict) -> Prediction:
        """Extract a prediction from a simulation result dict and save it.

        Expected keys in simulation_result:
            simulation_id, question_he, predicted_outcome,
            predicted_votes_for, predicted_votes_against,
            predicted_swing_mks (list), confidence (float)
        """
        prediction = Prediction(
            prediction_id=str(uuid.uuid4()),
            simulation_id=simulation_result.get("simulation_id", "unknown"),
            created_at=datetime.now(timezone.utc).isoformat(),
            question_he=simulation_result.get("question_he", ""),
            predicted_outcome=simulation_result.get("predicted_outcome", "unknown"),
            predicted_votes_for=simulation_result.get("predicted_votes_for", 0),
            predicted_votes_against=simulation_result.get("predicted_votes_against", 0),
            predicted_swing_mks=simulation_result.get("predicted_swing_mks", []),
            confidence=simulation_result.get("confidence", 0.5),
        )
        self._save(prediction)
        logger.info(
            "Recorded prediction %s for sim %s (confidence=%.2f)",
            prediction.prediction_id, prediction.simulation_id, prediction.confidence,
        )
        return prediction

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_prediction(self, prediction_id: str, actual_outcome: dict) -> dict:
        """Compare predicted vs actual and compute accuracy score.

        actual_outcome keys:
            outcome (str), votes_for (int), votes_against (int),
            swing_mks (list[str]) — MKs who actually swung their vote

        Accuracy breakdown (weighted):
            outcome_match:   1.0 if same, 0.0 if different   (weight 0.5)
            vote_accuracy:   1.0 - |predicted - actual| / 120 (weight 0.3)
            swing_accuracy:  fraction of predicted swing MKs   (weight 0.2)
        """
        pred = self._cache.get(prediction_id)
        if pred is None:
            raise KeyError(f"Prediction {prediction_id} not found")

        actual_result = actual_outcome.get("outcome", "unknown")
        actual_for = actual_outcome.get("votes_for", 0)
        actual_against = actual_outcome.get("votes_against", 0)
        actual_swing = set(actual_outcome.get("swing_mks", []))

        # Outcome match (weight 0.5)
        outcome_match = 1.0 if pred.predicted_outcome == actual_result else 0.0

        # Vote accuracy (weight 0.3) — based on combined for+against error
        vote_error_for = abs(pred.predicted_votes_for - actual_for)
        vote_error_against = abs(pred.predicted_votes_against - actual_against)
        avg_vote_error = (vote_error_for + vote_error_against) / 2.0
        vote_accuracy = max(0.0, 1.0 - avg_vote_error / 120.0)

        # Swing accuracy (weight 0.2) — fraction of predicted swing MKs correct
        if pred.predicted_swing_mks:
            predicted_swing = set(pred.predicted_swing_mks)
            correct_swings = predicted_swing & actual_swing
            swing_accuracy = len(correct_swings) / len(predicted_swing)
        else:
            swing_accuracy = 1.0 if not actual_swing else 0.0

        accuracy_score = (
            0.5 * outcome_match
            + 0.3 * vote_accuracy
            + 0.2 * swing_accuracy
        )

        # Update prediction
        pred.actual_outcome = actual_result
        pred.actual_votes_for = actual_for
        pred.actual_votes_against = actual_against
        pred.validated_at = datetime.now(timezone.utc).isoformat()
        pred.accuracy_score = round(accuracy_score, 4)
        self._save(pred)

        breakdown = {
            "outcome_match": outcome_match,
            "vote_accuracy": round(vote_accuracy, 4),
            "swing_accuracy": round(swing_accuracy, 4),
            "vote_error_for": vote_error_for,
            "vote_error_against": vote_error_against,
        }

        calibration_advice = self._generate_calibration_advice(breakdown, pred)

        logger.info(
            "Validated prediction %s: accuracy=%.3f outcome=%s",
            prediction_id, accuracy_score, "correct" if outcome_match else "wrong",
        )

        return {
            "prediction_id": prediction_id,
            "accuracy_score": pred.accuracy_score,
            "breakdown": breakdown,
            "calibration_advice": calibration_advice,
        }

    def _generate_calibration_advice(self, breakdown: dict, pred: Prediction) -> str:
        """Generate Hebrew calibration advice based on accuracy breakdown."""
        advice_parts: List[str] = []

        if breakdown["outcome_match"] == 0.0:
            if pred.predicted_outcome == "passed":
                advice_parts.append("הסימולציה חזתה העברה אך ההצעה נכשלה — יש לכייל לכיוון שמרני יותר.")
            else:
                advice_parts.append("הסימולציה חזתה כישלון אך ההצעה עברה — יש לכייל לכיוון אופטימי יותר.")

        if breakdown["vote_accuracy"] < 0.7:
            advice_parts.append(
                f"סטייה גבוהה בספירת הצבעות (שגיאה ממוצעת: "
                f"{(breakdown['vote_error_for'] + breakdown['vote_error_against']) / 2:.0f} קולות)."
            )

        if breakdown["swing_accuracy"] < 0.5:
            advice_parts.append("זיהוי חברי כנסת מתנדנדים היה חלש — יש לשפר מודל הנאמנות.")

        return " ".join(advice_parts) if advice_parts else "הכיול תקין, אין המלצות מיוחדות."

    # ------------------------------------------------------------------
    # Calibration statistics
    # ------------------------------------------------------------------

    def get_calibration_stats(self) -> dict:
        """Aggregate accuracy stats across all validated predictions."""
        validated = [p for p in self._cache.values() if p.accuracy_score is not None]
        total = len(self._cache)

        if not validated:
            return {
                "overall_accuracy": None,
                "outcome_accuracy": None,
                "vote_mae": None,
                "confidence_calibration": {},
                "bias": None,
                "total_predictions": total,
                "total_validated": 0,
            }

        # Overall accuracy
        overall = sum(p.accuracy_score for p in validated) / len(validated)

        # Outcome accuracy (% correct pass/fail)
        outcome_correct = sum(
            1 for p in validated if p.predicted_outcome == p.actual_outcome
        )
        outcome_accuracy = outcome_correct / len(validated)

        # Vote MAE
        vote_errors: List[float] = []
        for p in validated:
            if p.actual_votes_for is not None:
                vote_errors.append(abs(p.predicted_votes_for - p.actual_votes_for))
            if p.actual_votes_against is not None:
                vote_errors.append(abs(p.predicted_votes_against - p.actual_votes_against))
        vote_mae = sum(vote_errors) / len(vote_errors) if vote_errors else None

        # Confidence calibration — bucket by confidence, check actual accuracy
        buckets: Dict[str, List[float]] = {
            "0.0-0.2": [], "0.2-0.4": [], "0.4-0.6": [],
            "0.6-0.8": [], "0.8-1.0": [],
        }
        for p in validated:
            if p.confidence < 0.2:
                key = "0.0-0.2"
            elif p.confidence < 0.4:
                key = "0.2-0.4"
            elif p.confidence < 0.6:
                key = "0.4-0.6"
            elif p.confidence < 0.8:
                key = "0.6-0.8"
            else:
                key = "0.8-1.0"
            correct = 1.0 if p.predicted_outcome == p.actual_outcome else 0.0
            buckets[key].append(correct)

        confidence_calibration = {
            bucket: round(sum(vals) / len(vals), 3) if vals else None
            for bucket, vals in buckets.items()
        }

        # Bias — tendency to over-predict pass or fail
        pass_predictions = sum(1 for p in validated if p.predicted_outcome == "passed")
        pass_actual = sum(1 for p in validated if p.actual_outcome == "passed")
        if len(validated) > 0:
            bias_direction = "over_pass" if pass_predictions > pass_actual else (
                "over_fail" if pass_predictions < pass_actual else "neutral"
            )
            bias_magnitude = abs(pass_predictions - pass_actual) / len(validated)
        else:
            bias_direction = "neutral"
            bias_magnitude = 0.0

        return {
            "overall_accuracy": round(overall, 4),
            "outcome_accuracy": round(outcome_accuracy, 4),
            "vote_mae": round(vote_mae, 2) if vote_mae is not None else None,
            "confidence_calibration": confidence_calibration,
            "bias": {"direction": bias_direction, "magnitude": round(bias_magnitude, 4)},
            "total_predictions": total,
            "total_validated": len(validated),
        }

    def get_calibration_prompt_modifier(self) -> str:
        """Return Hebrew text to inject into agent prompts based on past accuracy.

        Designed to nudge the LLM toward more accurate predictions based on
        observed systematic errors.
        """
        stats = self.get_calibration_stats()

        if stats["total_validated"] < 3:
            return ""  # Not enough data to calibrate

        parts: List[str] = []

        # Bias correction
        bias = stats.get("bias", {})
        if bias.get("direction") == "over_pass" and bias.get("magnitude", 0) > 0.15:
            parts.append(
                "שים לב: בסימולציות קודמות נטינו לחזות יותר מדי הצבעות בעד. כייל בהתאם."
            )
        elif bias.get("direction") == "over_fail" and bias.get("magnitude", 0) > 0.15:
            parts.append(
                "שים לב: בסימולציות קודמות נטינו לחזות יותר מדי כישלונות. כייל בהתאם."
            )

        # Vote accuracy nudge
        if stats["vote_mae"] is not None and stats["vote_mae"] > 15:
            parts.append(
                f"סטיית הצבעות ממוצעת: {stats['vote_mae']:.0f} קולות. "
                "נסה לדייק יותר בחיזוי מספר ההצבעות."
            )

        # Overall performance note
        if stats["overall_accuracy"] is not None and stats["overall_accuracy"] < 0.5:
            parts.append(
                "דיוק כללי נמוך. שקול מחדש את הנחות הבסיס לגבי נאמנות סיעתית ולחצים קואליציוניים."
            )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Listing & export
    # ------------------------------------------------------------------

    def list_predictions(self, validated_only: bool = False) -> List[dict]:
        """Return all predictions with status."""
        results: List[dict] = []
        for pred in sorted(self._cache.values(), key=lambda p: p.created_at, reverse=True):
            if validated_only and pred.accuracy_score is None:
                continue
            d = pred.to_dict()
            d["status"] = "validated" if pred.accuracy_score is not None else "pending"
            results.append(d)
        return results

    def export_report(self) -> dict:
        """Full calibration report for display."""
        stats = self.get_calibration_stats()
        predictions = self.list_predictions()
        return {
            "calibration": stats,
            "prompt_modifier": self.get_calibration_prompt_modifier(),
            "predictions": predictions,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
