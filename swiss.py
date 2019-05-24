# -*- encoding: utf-8 -*- python3
"""Solver for swiss pairings."""

from __future__ import print_function

import argparse
import collections
import contextlib
import fractions
import itertools
import math
import random
import sys
from typing import List, Optional, Tuple

import blitzstein_diaconis
import networkx
import player as player_lib
import sheet_manager

flags = argparse.ArgumentParser(description='Calculate multi-swiss pairings.')
flags.add_argument(
    'set_code',
    metavar='XYZ',
    type=str,
    help='the set code for the pairings spreadsheet',
)
flags.add_argument(
    'cycle',
    metavar='n',
    type=int,
    help='the cycle number to pair',
)
flags.add_argument(
    '-w',
    '--write',
    action='store_true',
    help='whether to write the pairings to the spreadsheet',
)
flags.add_argument(
    '-t',
    '--timeout',
    metavar='n',
    type=int,
    default=600,
    help='time limit in seconds',
)
FLAGS = None  # Parsing the flags needs to happen in main.
EFFECTIVE_INFINITY = 1 << 26


def Odd(n):
  return n % 2 == 1


def Even(n):
  return not Odd(n)


def Lcm(a, b):
  """Compute the lowest common multiple."""
  return a * b // math.gcd(a, b)


def PrintPairings(pairings, lcm, stream=sys.stdout):
  """Print a pretty table of the model to the given stream."""
  my_pairings = sorted(
      ((abs(a.score - b.score), (a, b)) for (a, b) in pairings), reverse=True)
  final_loss = 0
  with contextlib.redirect_stdout(stream):
    for mismatch, (a, b) in my_pairings:
      # 7 + 7 + 28 + 28 + 4 spaces + "vs." (3) = 77
      a_score = f'({a.score})'
      b_score = f'({b.score})'
      line = f'{a_score:>7} {a.name:>28} vs. {b.name:<28} {b_score:>7}'
      if mismatch and stream.isatty():
        final_loss += mismatch * lcm**2
        line = '\033[1m{}\033[0m'.format(line)
      print(line)
    print()
    print(f'Total loss over LCM²: {final_loss} / {lcm**2}')
    rmse = math.sqrt(final_loss / lcm**2 / len(pairings))
    print(f'Root Mean Squared Error (per match): {rmse:.4f}')
  return final_loss


Pairings = List[Tuple[player_lib.Player, player_lib.Player]]

BYE = player_lib.Player('noreply', 'BYE', fractions.Fraction(0), 0, frozenset())


class Pairer(object):
  """Manages pairing a cycle of a league."""

  def __init__(self, players: List[player_lib.Player]):
    players = [p for p in players if p.requested_matches > 0]
    self.players = players
    self.players_by_id = {player.id: player for player in players}
    self.bye = None
    self.lcm = 1

  def GiveBye(self) -> Optional[player_lib.Player]:
    """Give a player a bye and return that player."""
    if Odd(sum(p.requested_matches for p in self.players)):
      eligible_players = [
          p for p in self.players if p.requested_matches == 3
          if BYE not in p.opponents
      ]
      # bye = min(eligible_players, key=lambda p: (p.score, random.random()))
      bye = self.players_by_id['sebh']
      self.players.remove(bye)
      self.bye = bye._replace(requested_matches=bye.requested_matches - 1)
      self.players.append(self.bye)
      return self.bye

  def RandomPairings(self) -> Pairings:
    """Generate and return random pairings."""
    degree_sequence = sorted(p.requested_matches for p in self.players)
    edge_set = blitzstein_diaconis.ImportanceSampledBlitzsteinDiaconis(
        degree_sequence)
    pairings = []
    players_by_index = dict(zip(itertools.count(), self.players))
    for (i, j) in edge_set:
      pairings.append((players_by_index[i], players_by_index[j]))

    if self.bye:
      pairings.append((self.bye, BYE))
    return pairings

  def Search(self, random_pairings=False) -> Pairings:
    """Constructs an SMT problem for pairings and optimizes it."""
    if random_pairings:
      print('Random pairings')
      return self.RandomPairings()

    for d in set(p.score.denominator for p in self.players):
      self.lcm = Lcm(self.lcm, d)

    graph = networkx.Graph()
    for p in self.players:
      p_nodes = [p.id + f'_{i}' for i in range(1, p.requested_matches + 1)]
      for node in p_nodes:
        graph.add_node(node)
    for p in self.players:
      for q in self.players:
        if p < q and q.id not in p.opponents:
          p_nodes = [p.id + f'_{i}' for i in range(1, p.requested_matches + 1)]
          for u, v in itertools.product(p_nodes, [f'{q.id}_1']):
            graph.add_edge(
                u,
                v,
                weight=-(int(p.score * self.lcm) - int(q.score * self.lcm))**2)
    while True:
      print(graph.size())
      matching = networkx.max_weight_matching(graph, maxcardinality=True)
      pairings = []
      bag = collections.Counter()
      for match in matching:
        canonical_form = tuple(
            sorted([
                match[0].rsplit('_', maxsplit=1)[0],
                match[1].rsplit('_', maxsplit=1)[0],
            ]))
        pairings.append(canonical_form)
        bag.update([canonical_form])
      print(bag.most_common(1))
      if bag.most_common(1)[0][1] == 1:
        break
      for match, multiplicity in bag.most_common(1):
        pid, qid = match
        for (p_node, q_node) in matching:
          if p_node.startswith(pid) and q_node.startswith(qid):
            graph.remove_edge(p_node, q_node)
            multiplicity -= 1
            if multiplicity == 1:
              break
    n = sum(p.requested_matches for p in self.players) // 2
    print(
        f'I have {len(pairings)} matches. I should have {n} (not counting BYE).'
    )
    pairings = [(self.players_by_id[pid], self.players_by_id[qid])
                for (pid, qid) in pairings]
    pairings.append((self.bye, BYE))
    return pairings


def Main():
  """Fetch records from the spreadsheet, generate pairings, write them back."""
  sheet = sheet_manager.SheetManager(FLAGS.set_code, FLAGS.cycle)
  pairer = Pairer(sheet.GetPlayers())
  pairer.GiveBye()
  loss = 91238409
  while loss > 145:
    pairings = pairer.Search(random_pairings=FLAGS.cycle in (1,))
    loss = PrintPairings(pairings, pairer.lcm)
  with open(f'pairings-{FLAGS.set_code}{FLAGS.cycle}.txt', 'w') as output:
    PrintPairings(pairings, pairer.lcm, stream=output)

  if FLAGS.write:
    sheet.Writeback(pairings)


if __name__ == '__main__':
  FLAGS = flags.parse_args(sys.argv[1:])
  Main()
