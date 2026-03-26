#!/usr/bin/env python3
"""
ig_graph_api.py — Instagram Graph API 기반 프로필 수집 (Cloud-ready)

로컬: assets/.env 파일에서 자격증명 로드
클라우드: Streamlit Secrets에서 자격증명 로드
"""

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

GRAPH_API_BASE = "https://graph.instagram.com/v21.0"
SKILL_DIR = Path(__file__).parent
ENV_FILE = SKILL_DIR / "assets" / ".env"
TOKEN_CACHE_FILE = SKILL_DIR / "assets" / "token_cache.json"


def load_env() -> dict:
    env = {}

    # 1순위: 로컬 .env 파일
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()

    # 2순위: Streamlit Secrets (클라우드 배포)
    try:
        import streamlit as st
        for key in ("IG_USER_ID", "IG_ACCESS_TOKEN", "FB_APP_ID", "FB_APP_SECRET"):
            if key in st.secrets:
                env[key] = st.secrets[key]
    except Exception:
        pass

    # 3순위: OS 환경변수 (최우선)
    for key in ("IG_USER_ID", "IG_ACCESS_TOKEN", "FB_APP_ID", "FB_APP_SECRET"):
        env[key] = os.environ.get(key, env.get(key, ""))

    return env


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def refresh_long_lived_token(token: str) -> str:
    """Instagram Login API 장기 토큰 갱신 (60일 유효)."""
    url = (
        f"{GRAPH_API_BASE}/refresh_access_token"
        f"?grant_type=ig_refresh_token"
        f"&access_token={token}"
    )
    data = _get(url)
    new_token = data.get("access_token", token)
    expires_in = data.get("expires_in", 0)

    cache = {"refreshed_at": datetime.now().isoformat(), "expires_in_seconds": expires_in}
    TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_FILE.write_text(json.dumps(cache, indent=2))
    print(f"[토큰 갱신] 완료. 유효기간: {expires_in // 86400}일")
    return new_token


def check_and_refresh_token(days_threshold: int = 45) -> str | None:
    """토큰 생성 후 days_threshold일 이상 경과 시 자동 갱신."""
    env = load_env()
    token = env.get("IG_ACCESS_TOKEN", "")
    if not token:
        return None

    if TOKEN_CACHE_FILE.exists():
        cache = json.loads(TOKEN_CACHE_FILE.read_text())
        refreshed_at = datetime.fromisoformat(cache.get("refreshed_at", "2000-01-01"))
        elapsed = (datetime.now() - refreshed_at).days
        if elapsed < days_threshold:
            print(f"[토큰 갱신] 마지막 갱신 {elapsed}일 전 — 갱신 불필요 ({days_threshold}일 기준)")
            return None
    else:
        cache = {"refreshed_at": datetime.now().isoformat(), "expires_in_seconds": 5184000}
        TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE_FILE.write_text(json.dumps(cache, indent=2))
        print("[토큰 갱신] 초기 캐시 생성 — 갱신 불필요")
        return None

    new_token = refresh_long_lived_token(token)
    if ENV_FILE.exists():
        content = ENV_FILE.read_text()
        old_line = next((l for l in content.splitlines() if l.startswith("IG_ACCESS_TOKEN=")), "")
        if old_line:
            content = content.replace(old_line, f"IG_ACCESS_TOKEN={new_token}")
            ENV_FILE.write_text(content)
            print("[토큰 갱신] assets/.env 업데이트 완료")
    return new_token


def fetch_profile_graph_api(user_id: str, access_token: str) -> dict:
    fields = "username,name,followers_count,follows_count,media_count,profile_picture_url,biography"
    url = f"{GRAPH_API_BASE}/{user_id}?fields={fields}&access_token={access_token}"

    try:
        data = _get(url)
    except Exception as e:
        raise RuntimeError(f"Graph API 호출 실패: {e}")

    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"Graph API 오류 [{err.get('code')}]: {err.get('message')}")

    return {
        "username": data.get("username", ""),
        "full_name": data.get("name", ""),
        "follower_count": data.get("followers_count", 0),
        "following_count": data.get("follows_count", 0),
        "media_count": data.get("media_count", 0),
        "profile_pic_url": data.get("profile_picture_url"),
        "is_private": False,
        "is_verified": False,
        "fetched_at": datetime.now().isoformat(),
        "source": "graph_api",
    }


def fetch_profile(target_username: str | None = None) -> dict:
    env = load_env()
    user_id = env.get("IG_USER_ID", "")
    token = env.get("IG_ACCESS_TOKEN", "")

    if not user_id or not token:
        raise RuntimeError(
            "IG_USER_ID, IG_ACCESS_TOKEN 미설정.\n"
            "로컬: assets/.env 파일 확인\n"
            "클라우드: Streamlit Secrets 설정 필요"
        )

    profile = fetch_profile_graph_api(user_id, token)

    if target_username and profile["username"] != target_username:
        print(
            f"[경고] IG_USER_ID({user_id})의 계정명 '{profile['username']}'이 "
            f"요청한 '{target_username}'과 다릅니다."
        )

    return profile
