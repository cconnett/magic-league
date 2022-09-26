"""OAuth2 authentication for magic-ny league parings."""

import gspread


def GetGc():
  return gspread.oauth(credentials_filename='credentials.json')
