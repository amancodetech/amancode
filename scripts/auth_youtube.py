"""Interactive YouTube OAuth authorization runner for AmanCode."""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow
from amancore.social.youtube import CLIENT_SECRET_FILE, SCOPES, TOKENS_FILE, YouTubeClient

def main():
    print("=" * 60)
    print("🚀 AmanCode YouTube Channel Integration Setup")
    print("=" * 60)
    
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_FILE),
        SCOPES
    )
    
    # Run local server to catch token automatically
    print("\n🌐 Starting local auth server...")
    print("👉 If a browser doesn't open automatically, open the link printed below:")
    
    creds = flow.run_local_server(
        host="localhost",
        port=8088,
        authorization_prompt_message="Please visit this URL to authorize AmanCode: {url}",
        success_message="✅ AmanCode YouTube Authorization Successful! You can close this window now.",
        open_browser=False
    )
    
    tokens_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    import json
    TOKENS_FILE.write_text(json.dumps(tokens_data, indent=2))
    print(f"\n🎉 Tokens saved successfully to: {TOKENS_FILE}")
    
    # Test channel info
    yt = YouTubeClient()
    info = yt.get_channel_info()
    print("\n📊 Connected YouTube Channel Details:")
    for k, v in info.items():
        print(f"  • {k}: {v}")
    print("\n✅ YouTube integration is 100% active and ready!")

if __name__ == "__main__":
    main()
