"""AmanCode YouTube Automation & Social Engine.

Handles:
- OAuth2 token management & auto-refresh (YouTube Data API v3).
- Channel analytics, stats, and profile details.
- Video & Short auto-upload with brand metadata.
- Automated comment monitoring, sentiment analysis, and AI replies.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..log import get_logger

log = get_logger("social.youtube")

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.upload",
]

CLIENT_SECRET_FILE = Path("/home/omar/Desktop/work/aman-core/configs/youtube_client_secret.json")
TOKENS_DIR = Path("/home/omar/Desktop/work/aman-core/bridge_data/youtube_session")
TOKENS_FILE = TOKENS_DIR / "tokens.json"


class YouTubeClient:
    def __init__(self, client_secret_file: Path = CLIENT_SECRET_FILE, tokens_file: Path = TOKENS_FILE):
        self.client_secret_file = client_secret_file
        self.tokens_file = tokens_file
        self.tokens_dir = tokens_file.parent
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        self.service = None
        self._load_service()

    def _load_service(self):
        if self.tokens_file.exists():
            try:
                data = json.loads(self.tokens_file.read_text())
                creds = Credentials.from_authorized_user_info(data, SCOPES)
                self.service = build("youtube", "v3", credentials=creds)
                log.info("YouTube API service initialized with stored credentials")
            except Exception as e:
                log.warning("Failed to load YouTube credentials from tokens file: %s", e)
                self.service = None

    def is_authenticated(self) -> bool:
        return self.service is not None

    def get_auth_url(self) -> str:
        """Returns the Google authorization URL for user to grant access."""
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secret_file),
            SCOPES,
            redirect_uri="http://localhost:8765/oauth2callback"
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"
        )
        return auth_url

    def complete_auth_with_code(self, code: str) -> Dict[str, Any]:
        """Exchanges auth code for access & refresh tokens and stores them."""
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secret_file),
            SCOPES,
            redirect_uri="http://localhost:8765/oauth2callback"
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        tokens_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
        self.tokens_file.write_text(json.dumps(tokens_data, indent=2))
        self.service = build("youtube", "v3", credentials=creds)
        log.info("YouTube OAuth2 flow completed and tokens saved")
        return self.get_channel_info()

    def get_channel_info(self) -> Dict[str, Any]:
        """Fetches the authenticated user's YouTube channel details."""
        if not self.service:
            raise RuntimeError("YouTube client not authenticated")
        
        request = self.service.channels().list(
            part="snippet,contentDetails,statistics",
            mine=True
        )
        response = request.execute()
        items = response.get("items", [])
        if not items:
            return {"error": "No channel found for authenticated account"}
        
        ch = items[0]
        snippet = ch.get("snippet", {})
        stats = ch.get("statistics", {})
        return {
            "id": ch.get("id"),
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "custom_url": snippet.get("customUrl"),
            "published_at": snippet.get("publishedAt"),
            "subscribers": stats.get("subscriberCount", "0"),
            "views": stats.get("viewCount", "0"),
            "videos_count": stats.get("videoCount", "0"),
            "avatar_url": snippet.get("thumbnails", {}).get("high", {}).get("url"),
        }

    def list_recent_comments(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """Fetches recent top-level comments on the channel's videos."""
        if not self.service:
            raise RuntimeError("YouTube client not authenticated")
        
        request = self.service.commentThreads().list(
            part="snippet,replies",
            allThreadsRelatedToChannelId=self.get_channel_info().get("id"),
            maxResults=max_results,
            order="time"
        )
        response = request.execute()
        comments = []
        for item in response.get("items", []):
            top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            comments.append({
                "id": item.get("id"),
                "video_id": item.get("snippet", {}).get("videoId"),
                "author": top.get("authorDisplayName"),
                "author_channel_id": top.get("authorChannelId", {}).get("value"),
                "text": top.get("textDisplay"),
                "published_at": top.get("publishedAt"),
                "like_count": top.get("likeCount", 0),
            })
        return comments

    def reply_to_comment(self, comment_thread_id: str, text: str) -> Dict[str, Any]:
        """Replies to a comment thread."""
        if not self.service:
            raise RuntimeError("YouTube client not authenticated")
        
        request = self.service.comments().insert(
            part="snippet",
            body={
                "snippet": {
                    "parentId": comment_thread_id,
                    "textOriginal": text
                }
            }
        )
        return request.execute()

    def upload_video(
        self,
        file_path: str,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category_id: str = "28", # 28 = Science & Technology
        privacy_status: str = "public",
        is_short: bool = False
    ) -> Dict[str, Any]:
        """Uploads a video or Short to YouTube."""
        if not self.service:
            raise RuntimeError("YouTube client not authenticated")
        
        body = {
            "snippet": {
                "title": f"{title} #Shorts" if is_short and "#Shorts" not in title else title,
                "description": description,
                "tags": tags or ["AmanCode", "Software", "AI", "ERP", "WebDevelopment"],
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
        request = self.service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("Uploaded %d%% of video", int(status.progress() * 100))
        
        log.info("Video uploaded successfully: id=%s", response.get("id"))
        return response
