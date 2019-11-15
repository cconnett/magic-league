# python3
"""Solver for swiss pairings."""

import collections
import contextlib
import difflib
import enum
import fractions
import itertools
import math
import multiprocessing
import os
import random
import sys
import time

from typing import List, Optional, Tuple
from absl import app
from absl import flags

import blitzstein_diaconis
import elkai
import numpy as np
import player as player_lib
import sheet_manager

BYE = player_lib.Player('noreply', 'BYE', fractions.Fraction(0), 0, ())
EFFECTIVE_INFINITY = (1 << 31) - 1
FLAGS = flags.FLAGS
HUB_COST = 1
MAX_LCM = 10080  # 2 × 7!
MAX_PROCESSES = multiprocessing.cpu_count()

Pairings = List[Tuple[player_lib.Player, player_lib.Player]]

flags.DEFINE_bool(
    'write', False, 'Write the pairings to the spreadsheet', short_name='w')
flags.DEFINE_bool(
    'fetch',
    False,
    'Force a fetch from the sheet, overriding the 20 minute cache timeout.',
    short_name='f')


def Odd(n):
  return n % 2 == 1


def Even(n):
  return not Odd(n)


def Lcm(a, b):
  """Compute the lowest common multiple."""
  return a * b // math.gcd(a, b)


def SSE(pairings):
  """Returns the sum of squared error (SSE) of pairings."""
  return sum((p.score - q.score)**2 for (p, q) in pairings)


def ValidatePairings(pairings: Pairings, n: Optional[int] = None) -> None:
  """Raises an error if the pairings aren't valid.

  Args:
    pairings: The proposed pairings.
    n: The expected number of pairings.

  Raises:
    WrongNumberOfMatchesError: There were not `n` matches.
    DuplicateMatchError: If the proposed pairings contain a duplicate.
    RepeatMatchError: If the proposed contain a match that occurred in a
    previous cycle.
  """
  if n is not None and len(pairings) != n:
    raise WrongNumberOfMatchesError(
        f'There are {len(pairings)} matches, but {n} were expected.')
  if len(set(tuple(sorted(match)) for match in pairings)) < len(pairings):
    # Duplicate matches
    matches = collections.Counter(tuple(sorted(match)) for match in pairings)
    dupes = []
    while matches:
      match, multiplicity = matches.most_common(1)[0]
      if multiplicity > 1:
        dupes.append(f'({match[0].id}, {match[1].id})')
        matches.pop(match)
      else:
        break
    if dupes:
      raise DuplicateMatchError(' '.join(dupes))
  for p, q in pairings:
    if p == q or p.id in q.opponents or q.id in p.opponents:
      raise RepeatMatchError(f'{p.id}, {q.id}')


def PrintPairings(pairings, stream=sys.stdout):
  """Print a pretty table of the model to the given stream."""
  with contextlib.redirect_stdout(stream):
    for (p, q) in pairings:
      # 7 + 7 + 28 + 28 + 4 spaces + "vs." (3) = 77
      p_score = f'({p.score})'
      q_score = f'({q.score})'
      line = f'{p_score:>7} {p.name:>28} vs. {q.name:<28} {q_score:>7}'
      if abs(p.score - q.score) > 0:
        if stream.isatty():
          line = f'\033[1m{line}\033[0m'
      print(line)
    print()
    loss = SSE(pairings)
    approx_loss = loss.limit_denominator(1000)
    approx_string = 'Approx. ' if approx_loss != loss else ''
    print(f'Sum of squared error: {approx_string}{approx_loss!s}')
    rmse = math.sqrt(SSE(pairings) / len(pairings))
    print(f'Root Mean Squared Error (per match): {rmse:.4f}')


class NodeType(enum.Enum):
  REQUESTED_MATCH = 1
  MATCHUP = 2


class Pairer(object):
  """Manages pairing a cycle of a league."""

  def __init__(self, players: List[player_lib.Player]):
    self.players = [p for p in players if p.requested_matches > 0]
    self.players_by_id = {player.id: player for player in players}
    self.byed_player = None
    self.lcm = 1
    for d in set(p.score.denominator for p in self.players):
      self.lcm = Lcm(self.lcm, d)

  @property
  def correct_num_matches(self):
    """Returns the number of non-BYE matches that there *should* be."""
    return sum(player.requested_matches for player in self.players) // 2

  def GiveBye(self) -> Optional[player_lib.Player]:
    """Select a byed player if one is needed.

    If the total number of requested matches is odd, a bye is needed. Select a
    random 3-match-requester from among those with the lowest score. Mark that
    player as byed, decrease their requested matches, and return that player.
    It does NOT add a match representing the bye to any list of pairings.

    If the total number of requested matches is even, return None.

    Returns:
      The Player object of the player that got the bye.
    """
    if Odd(sum(p.requested_matches for p in self.players)):
      eligible_players = [
          p for p in self.players if p.requested_matches == 3
          if BYE.id not in p.opponents
      ]
      byed_player = min(
          eligible_players, key=lambda p: (p.score, random.random()))
      self.players.remove(byed_player)
      self.byed_player = byed_player._replace(
          requested_matches=byed_player.requested_matches - 1)
      self.players.append(self.byed_player)
      return self.byed_player

  def MakePairings(self, random_pairings=False) -> Pairings:
    """Make pairings — random in cycle 1, else TSP optimized."""
    if random_pairings:
      print('Random pairings')
      pairings = self.RandomPairings()
    else:
      # print('Optimizing pairings')
      pairings = self.TravellingSalesPairings()
    ValidatePairings(pairings, n=self.correct_num_matches)
    if self.byed_player:
      pairings.append((self.byed_player, BYE))
      ValidatePairings(pairings, n=self.correct_num_matches + 1)
    return pairings

  def RandomPairings(self) -> Pairings:
    """Generate and return random pairings."""
    degree_sequence = [p.requested_matches for p in self.players]
    edge_set = blitzstein_diaconis.ImportanceSampledBlitzsteinDiaconis(
        degree_sequence)
    pairings = []
    players_by_index = dict(enumerate(self.players))
    for (i, j) in edge_set:
      pairings.append((players_by_index[i], players_by_index[j]))
    return pairings

  def TravellingSalesPairings(self):
    """Compute optimal pairings with a travelling-salesman solver."""
    odd_players = list(p for p in self.players if Odd(p.requested_matches))
    random.shuffle(odd_players)
    assert Even(len(odd_players))

    my_lcm = min(MAX_LCM, self.lcm)
    counter = itertools.count()
    depot = next(counter)
    requested_match_nodes = {}
    matchup_nodes = {}
    for p in self.players:
      for z in range(p.requested_matches):
        requested_match_nodes[(p, z)] = next(counter)
    for p in self.players:
      for q in self.players:
        if p >= q:
          continue
        if p.id in q.opponents or q.id in p.opponents:
          continue
        if abs(p.score - q.score) > 0.5:
          continue
        matchup_nodes.setdefault(p, {})[q] = next(counter)
    # In the next step, we're going to draw the edges between requested matches
    # and matchup nodes. They go only in the forward direction (from lower
    # indexed players to higher ones). This means the RMs of the last player
    # never go out to a matchup node. But that just means the path takes the
    # penalty to go to the next player / sends another veh.
    n = (
        len(requested_match_nodes) +
        sum(len(x) for x in matchup_nodes.values()) + 1)
    weights = np.full((n, n), EFFECTIVE_INFINITY, dtype=int)
    try:
      for (p, z) in requested_match_nodes:
        if p not in matchup_nodes:
          # The last player alphabetically won't have an entry in matchup_nodes.
          continue
        for q in matchup_nodes[p]:
          edge = (requested_match_nodes[(p, z)], matchup_nodes[p][q])
          # The edge from player 1 to matchup node is the cost.
          weights[edge] = (int(p.score * my_lcm) - int(q.score * my_lcm))**2
          # The edge from matchup node to player 2 is the 0.
          weights[matchup_nodes[p][q], requested_match_nodes[(q, 0)]] = 0
          if (q, 1) in requested_match_nodes:
            weights[matchup_nodes[p][q], requested_match_nodes[(q, 1)]] = 0
          if (q, 2) in requested_match_nodes:
            weights[matchup_nodes[p][q], requested_match_nodes[(q, 2)]] = 0
      # # Fill in a fixed rate for transitions between requested_match nodes.
      # for ma in requested_match_nodes.values():
      #   for mb in requested_match_nodes.values():
      #     weights[ma, mb] = 2 * my_lcm**2
      #     weights[mb, ma] = 2 * my_lcm**2

      # Paths to and from the depot are FREE.
      for node in requested_match_nodes.values():
        weights[depot, node] = weights[node, depot] = 0
    except:
      import pdb
      pdb.post_mortem()
      raise
    pairings = []
    # tour = elkai.solve_int_matrix(weights)
    print('NAME: Pairings')
    print('TYPE: ACVRP')
    print(f'DIMENSION: {n}')
    print('EDGE_WEIGHT_TYPE: EXPLICIT')
    print('EDGE_WEIGHT_FORMAT: FULL_MATRIX')
    print('EDGE_DATA_FORMAT: EDGE_LIST')
    print('CAPACITY: 1')
    print(f'VEHICLES: {len(requested_match_nodes)}')
    print('DEPOT_SECTION')
    print(f'{depot+1} -1')
    print('EDGE_DATA_SECTION')
    for i in range(n):
      for j in range(n):
        if i != j and weights[i][j] != EFFECTIVE_INFINITY:
          print(f'{i+1} {j+1} {weights[i, j]}')
    print('-1')
    print('DEMAND_SECTION')
    print(f'{depot+1} 0')
    for c in requested_match_nodes.values():
      print(f'{c+1} 1')
    for p in matchup_nodes:
      for d in matchup_nodes[p].values():
        print(f'{d+1} 0')
    print('EOF')

    reverse_nodes = {}
    for p in matchup_nodes:
      for q in matchup_nodes[p]:
        reverse_nodes[matchup_nodes[p][q]] = (p, q)
    for a, b in zip(tour, tour[1:]):
      if a in requested_match_nodes.values() and b in matchup_nodes.values():
        pairings.append(reverse_nodes[a])
    return pairings


def OrderPairingsByTsp(pairings: Pairings) -> Pairings:
  """Sort the given pairings by minimal cost tour."""
  pairings = pairings[:]
  random.shuffle(pairings)
  num_nodes = 2 * len(pairings) + 1
  weights = np.zeros((num_nodes, num_nodes), dtype=float)

  for alpha in range(len(pairings)):
    alpha_left = 2 * alpha + 1
    alpha_right = 2 * alpha + 2
    weights[alpha_left, alpha_right] = weights[alpha_right, alpha_left] = -1
    for beta in range(len(pairings)):
      if beta == alpha:
        continue
      beta_left = 2 * beta + 1
      beta_right = 2 * beta + 2
      # normal;normal
      # swapped;swapped
      weights[alpha_right, beta_left] = weights[alpha_left, beta_right] = (
          PairingTransitionCost(pairings[alpha], pairings[beta]))
      # normal;swapped
      # swapped;normal
      weights[alpha_right, beta_right] = weights[alpha_left, beta_left] = (
          PairingTransitionCost(pairings[alpha], pairings[beta][::-1]))
  tour = elkai.solve_float_matrix(weights)
  output_pairings = []
  for node in tour[1::2]:
    next_pairing = pairings[(node - 1) // 2]
    if node % 2 == 0:
      next_pairing = next_pairing[::-1]
    output_pairings.append(next_pairing)
  return output_pairings


def OrderPairingsByScore(pairings: Pairings) -> Pairings:
  return list(
      sorted(pairings, key=lambda t: (t[0].score, t[1].score, t), reverse=True))


def PairingTransitionCost(pairing_alpha, pairing_beta) -> float:
  left_cost = 1 - difflib.SequenceMatcher(
      a=pairing_alpha[0], b=pairing_beta[0]).ratio()
  right_cost = 1 - difflib.SequenceMatcher(
      a=pairing_alpha[1], b=pairing_beta[1]).ratio()
  return left_cost + right_cost


def Main(argv):
  """Fetch records from the spreadsheet, generate pairings, write them back."""
  set_code, cycle = argv[1:]
  cycle = int(cycle)

  sheet = sheet_manager.SheetManager(set_code, cycle)
  pairer = Pairer(sheet.GetPlayers())
  pairer.GiveBye()
  start = time.time()
  pairings = pairer.MakePairings(random_pairings=cycle in (1,))
  pairings = OrderPairingsByTsp(pairings)
  PrintPairings(pairings)
  ValidatePairings(
      pairings, n=pairer.correct_num_matches + bool(pairer.byed_player))
  t = time.time() - start
  try:
    os.mkdir('pairings')
  except FileExistsError:
    pass
  with open(f'pairings/pairings-{set_code}{cycle}.{int(time.time())}.txt',
            'w') as output:
    PrintPairings(pairings, stream=output)
  with open(f'pairings/pairings-{set_code}{cycle}.txt', 'w') as output:
    PrintPairings(pairings, stream=output)
  print(f'Finished in {int(t // 60)}m{t % 60:.1f}s wall time.')

  if FLAGS.write:
    sheet.Writeback(pairings)


class Error(Exception):
  pass


class DuplicateMatchError(Error):
  """The same match-up appears twice in this set of pairings."""


class RepeatMatchError(Error):
  """A match-up from a previous round appears in this set of pairings."""


class WrongNumberOfMatchesError(Error):
  """This set of pairings has the wrong number of matches."""


if __name__ == '__main__':
  app.run(Main)
