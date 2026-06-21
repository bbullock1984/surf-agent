name: Daily Surf Forecast Feed

on:
  schedule:
    - cron: "0 11 * * *"   # 11:00 UTC = ~7am EDT / 6am EST. Adjust as desired.
  workflow_dispatch: {}     # lets you trigger it manually from the Actions tab

permissions:
  contents: write

jobs:
  build-feed:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests

      - name: Build feed
        run: python fetch_and_build_feed.py

      - name: Commit and push updated feed
        run: |
          git config user.name "surf-feed-bot"
          git config user.email "actions@github.com"
          git add docs/feed.xml
          git diff --staged --quiet || git commit -m "Update daily surf forecast feed"
          git pull --rebase --autostash
          git push
