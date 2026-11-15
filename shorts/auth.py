"""One-time: run on YOUR computer to get a refresh token for the channel.

    pip install google-auth-oauthlib
    python auth.py client_secret.json

A browser opens -> log in to the channel's Google account -> allow.
Copy the printed values into GitHub Secrets (see README.md).
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from yt import SCOPES

path = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(path))["installed"]
print("\nYT_CLIENT_ID=" + info["client_id"])
print("YT_CLIENT_SECRET=" + info["client_secret"])
print("YT_REFRESH_TOKEN=" + creds.refresh_token)
