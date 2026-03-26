"""Knesset simulation platforms — pluggable interaction modes.

Each platform defines its own action set, prompt templates, and state
management, allowing the same KnessetLoop engine to run different
interaction patterns (plenum debate, roundtable, negotiation, etc.).
"""

from .base_platform import BasePlatform, PlatformAction
from .brainstorm import BrainstormPlatform
from .decision import DecisionPlatform
from .negotiation import NegotiationPlatform
from .plenum import PlenumPlatform
from .press_conference import PressConferencePlatform
from .roundtable import RoundtablePlatform

__all__ = [
    "BasePlatform",
    "PlatformAction",
    "PlenumPlatform",
    "RoundtablePlatform",
    "NegotiationPlatform",
    "BrainstormPlatform",
    "DecisionPlatform",
    "PressConferencePlatform",
]

PLATFORM_REGISTRY = {
    "plenum": PlenumPlatform,
    "roundtable": RoundtablePlatform,
    "negotiation": NegotiationPlatform,
    "brainstorm": BrainstormPlatform,
    "decision": DecisionPlatform,
    "press_conference": PressConferencePlatform,
}
