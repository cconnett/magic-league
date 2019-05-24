# python3
"""Player datatype."""
import fractions
from typing import NamedTuple, Set, Text

Name = Text
Username = Text


class Player(NamedTuple):
  id: Username
  name: Name
  score: fractions.Fraction
  requested_matches: int
  opponents: Set[Username]
