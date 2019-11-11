# python3
"""Liaison to Google Sheets."""

import datetime
import fractions
import itertools
import os
import pickle
import random

from absl import flags
import password
import player as player_lib

THURSDAY = 3


def CycleDeadline():
  today = datetime.date.today()
  weekday = today.weekday()
  cycle_length = (THURSDAY - weekday) % 7 + 7
  if cycle_length < 10:
    cycle_length += 7
  deadline = today + datetime.timedelta(days=cycle_length)
  return deadline


class SheetManager(object):
  """Marshals data to and from the Google Sheet."""

  def __init__(self, set_code, cycle):
    self.set_code = set_code
    self.cycle = cycle
    self.sheet = None

  def _ConnectToSheet(self):
    self.sheet = password.GetGc().open(
        f'magic-ny {self.set_code} Sealed League')

  def GetPlayers(self):
    player_list = self._FetchFromCache()
    random.shuffle(player_list)
    return player_list

  def Writeback(self, pairings):
    """Write the pairings to the sheet."""
    # Some aspect of the connection to the spreadsheet can go stale. Reload it
    # just before writing to make sure it's fresh.
    self._ConnectToSheet()

    ws_name = 'Cycle ' + str(self.cycle)
    output = self.sheet.worksheet(ws_name)
    pairings_range = output.range(f'B2:C{len(pairings) + 1}')

    flattened_pairings = itertools.chain.from_iterable(pairings)
    for cell, player in zip(pairings_range, flattened_pairings):
      cell.value = player.name
    print('Writing to', ws_name)
    output.update_acell('I1', CycleDeadline().strftime('%B %d'))
    output.update_cells(pairings_range)

  def _FetchFromCache(self):
    """Fetches data from local file, falling back to the spreadsheet."""

    filename = f'{self.set_code}-{self.cycle}'
    try:
      mtime = datetime.datetime.fromtimestamp(os.stat(filename).st_mtime)
      age = datetime.datetime.now() - mtime
      if age < datetime.timedelta(minutes=20) and not flags.FLAGS.fetch:
        player_list = pickle.load(open(filename, 'rb'))
        # print('Loaded previous results from cache')
        return player_list
    except (IOError, EOFError, FileNotFoundError):
      pass
    player_list = self._FetchFromSheet()
    pickle.dump(player_list, open(filename, 'wb'))
    return player_list

  def _FetchFromSheet(self):
    """Fetches data from the spreadsheet."""
    self._ConnectToSheet()
    standings = self.sheet.worksheet('Standings')
    names = list(standings.col_values(1)[1:])
    ids = list(standings.col_values(2)[1:])
    wins = [int(n) for n in standings.col_values(4)[1:]]
    losses = [int(n) for n in standings.col_values(5)[1:]]
    requested_matches = [
        int(s) for s in standings.col_values(10 + self.cycle - 1)[1:]
    ]
    scores = [
        fractions.Fraction(w, (w + l)) if w + l else fractions.Fraction(1, 2)
        for w, l in zip(wins, losses)
    ]

    previous_pairings = set()
    for i in range(1, self.cycle):
      cycle_sheet = self.sheet.worksheet(f'Cycle {i}')
      a = cycle_sheet.col_values(1)[1:]  # type: List[Username]
      b = cycle_sheet.col_values(4)[1:]  # type: List[Username]
      previous_pairings |= set(zip(a, b))
      previous_pairings |= set(zip(b, a))

    player_list = []
    for vitals in zip(ids, names, scores, requested_matches):
      id_, name, score, rm = vitals
      opponent_ids = frozenset(b for (a, b) in previous_pairings if id_ == a)
      player_list.append(player_lib.Player(id_, name, score, rm, opponent_ids))
    print('Fetched previous results from sheet')
    return player_list
