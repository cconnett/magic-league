# python3
"""Liaison to Google Sheets."""

import datetime
import fractions
import importlib
import itertools
import pickle
import random

import password
import player as player_lib

THURSDAY = 3


def CycleDeadline():
  today = datetime.date.today()
  weekday = today.weekday()
  deadline = today + datetime.timedelta(days=14 - weekday + THURSDAY)
  return deadline.strftime('%B %d')


class SheetManager(object):
  """Marshals data to and from the Google Sheet."""

  def __init__(self, set_code, cycle):
    self.set_code = set_code
    self.cycle = cycle
    self.sheet = password.gc.open(f'magic-ny {self.set_code} Sealed League')

  def GetPlayers(self):
    player_list = self._FetchFromCache()
    random.shuffle(player_list)
    return player_list

  def Writeback(self, pairings):
    """Write the pairings to the sheet."""
    # Some aspect of the connection to the spreadsheet can go stale. Reload it
    # just before writing to make sure it's fresh.
    global password
    password = importlib.reload(password)  # pylint: disable=redefined-outer-name

    ws_name = 'Cycle ' + str(self.cycle)
    output = self.sheet.worksheet(ws_name)
    pairings_range = output.range(f'B2:C{len(pairings) + 1}')

    flattened_pairings = itertools.chain.from_iterable(pairings)
    for cell, player in zip(pairings_range, flattened_pairings):
      cell.value = player.name
    print('Writing to', ws_name)
    output.update_acell('I1', CycleDeadline())
    output.update_cells(pairings_range)

  def _FetchFromCache(self, from_cache=True):
    """Fetches data from local file, falling back to the spreadsheet."""

    filename = '{s.set_code}-{s.cycle}'.format(s=self)
    if from_cache:
      try:
        return pickle.load(open(filename, 'rb'))
      except (IOError, EOFError):
        pass
    player_list = self._FetchFromSheet()
    pickle.dump(player_list, open(filename, 'wb'))
    return player_list

  def _FetchFromSheet(self):
    """Fetches data from the spreadsheet."""

    standings = self.sheet.worksheet('Standings')
    names = list(standings.col_values(1)[1:])
    ids = list(standings.col_values(2)[1:])
    wins = [int(n) for n in standings.col_values(4)[1:]]
    losses = [int(n) for n in standings.col_values(5)[1:]]
    draws = [int(n) for n in standings.col_values(6)[1:]]
    requested_matches = [
        int(s) for s in standings.col_values(9 + self.cycle - 1)[1:]
    ]

    scores = [
        fractions.Fraction(2 * w + d, 2 * (w + l + d)) if w + l +
        d else fractions.Fraction(1, 2) for w, l, d in zip(wins, losses, draws)
    ]

    previous_pairings = set()
    for i in range(1, self.cycle):
      cycle_sheet = self.sheet.worksheet('Cycle {}'.format(i))
      a = cycle_sheet.col_values(1)[1:]  # type: List[Username]
      b = cycle_sheet.col_values(4)[1:]  # type: List[Username]
      previous_pairings |= set(zip(a, b))
      previous_pairings |= set(zip(b, a))

    player_list = []
    for vitals in zip(ids, names, scores, requested_matches):
      name = vitals[0]
      opponent_ids = frozenset(b for (a, b) in previous_pairings if name == a)
      player_list.append(player_lib.Player(*(vitals + (opponent_ids,))))
    return player_list
