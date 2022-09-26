# magic-league

A Super-Swiss pairing algorithm for casual Magic: The Gathering leagues.

At my workplace, we have a recurring Magic: the Gathering sealed league. A
problem we faced was that people needed flexibility to play varying numbers of
matches. We also wanted to maintain the benefits of Swiss pairings.

This software uses the min-weight graph matching to assign matches in a way that
respects requested numbers of matches while minimizing differences in
win-percentage among the pairings. It can post those pairings directly to a
Google sheet that is specifically formatted.

## Setup

### Install prerequisites

```
pip install -r requirements.txt
```

### Create `credentials.json`

To connect to a spreadsheet for automatic import and export, you'll need to
download a OAuth Client ID and populate `credentials.json`.

1.  Follow the "OAuth Client ID" instructions at
    https://docs.gspread.org/en/v5.4.0/oauth2.html#authentication .
1.  Move the downloaded credentials file to `[project root]/credentials.json`.

When you run the script, a browser window will open to authorize the script to
read and write to your spreadsheets. We apologize for the extreme access
requested, but there does not seem to be a more suitable scope.

## Run

The most common invocation:

```
python3 swiss.py <set code> <cycle number> -w
```

or `--helpshort` for all the options.

## Template League Spreadsheet

The cells from which to read past pairings and to which to post new pairings are
hard-coded in `sheet_manager.py`. You can use [this template sheet][1] to track
your own league, or adapt `sheet_manager` to use ranges appropriate to an
existing sheet.

[1]: https://docs.google.com/spreadsheets/d/1wDgi1rTJ3bq7-i91jEPzho4gVGx2SAaKOSALNtz41CA/edit?usp=sharing
