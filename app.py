#!/usr/bin/env python3
"""
app.py — NoxInfluencer 스타일 Instagram 팔로워 라이브 카운터
Streamlit Community Cloud 배포용

로컬 실행: streamlit run app.py
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from ig_graph_api import fetch_profile

# ── 경로 설정 ─────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = ASSETS_DIR / "data"
CONFIG_FILE = ASSETS_DIR / "config.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    # 클라우드 기본값
    return {
        "targets": [{"username": "leandiet_official", "label": "린다이어트"}],
        "poll_interval_seconds": 300,
    }


def get_yesterday_count(target: str) -> int | None:
    for d in range(1, 8):
        date_str = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
        path = DATA_DIR / f"{target}_{date_str}.json"
        if path.exists():
            snap = json.loads(path.read_text())
            return snap["follower_count"]
    return None


def save_snapshot(target: str, count: int) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    path = DATA_DIR / f"{target}_{today}.json"
    snap = {
        "date": today,
        "collected_at": datetime.now().isoformat(),
        "target": target,
        "follower_count": count,
    }
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2))


def load_recent_snapshots(target: str, days: int = 7) -> list[dict]:
    result = []
    for d in range(days, 0, -1):
        date_str = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
        path = DATA_DIR / f"{target}_{date_str}.json"
        if path.exists():
            snap = json.loads(path.read_text())
            result.append({"date": date_str[5:], "count": snap["follower_count"]})
    return result


def render_live_counter(
    profile: dict,
    yesterday_count: int | None,
    trend: list[dict],
    refresh_interval: int,
):
    count = profile["follower_count"]
    username = profile["username"]
    full_name = profile["full_name"]
    media_count = profile.get("media_count", 0)
    following_count = profile.get("following_count", 0)

    daily_change = count - yesterday_count if yesterday_count else 0
    rate_per_ms = daily_change / 86_400_000

    if yesterday_count:
        sign = "+" if daily_change >= 0 else ""
        pct = round(daily_change / yesterday_count * 100, 2) if yesterday_count else 0
        delta_html = f"{sign}{daily_change:,}명 ({sign}{pct}%) <span style='color:#555;font-size:14px;font-weight:400'>vs 어제</span>"
        delta_color = "#2ecc71" if daily_change >= 0 else "#e74c3c"
    else:
        delta_html = "<span style='color:#444;font-size:14px'>어제 데이터 없음</span>"
        delta_color = "#555"

    spark_data = json.dumps([t["count"] for t in trend]) if trend else "[]"
    spark_labels = json.dumps([t["date"] for t in trend]) if trend else "[]"

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0d0d0d;
    color: #fff;
    font-family: 'Inter', -apple-system, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 32px 16px 24px;
    min-height: 100vh;
  }}

  .live-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(225,48,108,0.12);
    border: 1px solid rgba(225,48,108,0.3);
    color: #E1306C;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    padding: 5px 14px;
    border-radius: 20px;
    margin-bottom: 28px;
  }}
  .live-dot {{
    width: 7px; height: 7px;
    background: #E1306C;
    border-radius: 50%;
    animation: pulse 1.4s ease-in-out infinite;
  }}
  @keyframes pulse {{
    0%,100% {{ opacity:1; transform:scale(1); }}
    50% {{ opacity:0.25; transform:scale(0.6); }}
  }}

  .account {{ font-size: 13px; color: #555; letter-spacing: 1.5px; margin-bottom: 4px; }}
  .fullname {{ font-size: 20px; font-weight: 700; color: #eee; margin-bottom: 36px; }}

  .counter-block {{ text-align: center; margin-bottom: 6px; }}
  #live-count {{
    font-size: clamp(64px, 14vw, 100px);
    font-weight: 900;
    color: #fff;
    letter-spacing: -3px;
    line-height: 1;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
  }}
  .counter-label {{
    font-size: 11px;
    color: #333;
    letter-spacing: 4px;
    text-transform: uppercase;
    margin-bottom: 20px;
  }}

  .delta {{
    font-size: 18px;
    font-weight: 600;
    color: {delta_color};
    margin-bottom: 36px;
    min-height: 26px;
    text-align: center;
  }}

  .stats-row {{ display: flex; gap: 40px; margin-bottom: 36px; }}
  .stat {{ text-align: center; }}
  .stat-num {{ font-size: 20px; font-weight: 700; color: #ccc; }}
  .stat-label {{ font-size: 10px; color: #444; letter-spacing: 2px; text-transform: uppercase; margin-top: 2px; }}

  .progress-wrap {{ width: 260px; max-width: 90vw; margin-bottom: 8px; }}
  .progress-track {{ height: 2px; background: #1a1a1a; border-radius: 2px; overflow: hidden; }}
  #progress-fill {{
    height: 100%;
    background: linear-gradient(90deg, #E1306C, #833AB4, #405DE6);
    width: 0%;
    transition: width 0.8s linear;
  }}
  .refresh-text {{ font-size: 10px; color: #333; letter-spacing: 1px; text-align: center; margin-top: 6px; }}

  .spark-section {{ margin-top: 40px; width: 100%; max-width: 480px; }}
  .spark-title {{ font-size: 10px; color: #333; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 12px; text-align: center; }}
  canvas#spark {{ width: 100%; height: 80px; display: block; }}
  .spark-labels {{ display: flex; justify-content: space-between; margin-top: 6px; font-size: 9px; color: #333; }}

  @keyframes flash {{
    0% {{ color: #E1306C; }}
    100% {{ color: #fff; }}
  }}
  .flashing {{ animation: flash 0.4s ease forwards; }}
</style>
</head>
<body>

<div class="live-badge"><span class="live-dot"></span>LIVE</div>
<div class="account">@{username}</div>
<div class="fullname">{full_name}</div>

<div class="counter-block">
  <div id="live-count">{count:,}</div>
</div>
<div class="counter-label">팔로워</div>

<div class="delta">{delta_html}</div>

<div class="stats-row">
  <div class="stat">
    <div class="stat-num">{media_count:,}</div>
    <div class="stat-label">게시물</div>
  </div>
  <div class="stat">
    <div class="stat-num">{following_count:,}</div>
    <div class="stat-label">팔로잉</div>
  </div>
</div>

<div class="progress-wrap">
  <div class="progress-track"><div id="progress-fill"></div></div>
  <div class="refresh-text" id="refresh-text">데이터 로딩...</div>
</div>

<div class="spark-section" id="spark-section" style="display:none">
  <div class="spark-title">7일 추이</div>
  <canvas id="spark"></canvas>
  <div class="spark-labels" id="spark-labels"></div>
</div>

<script>
  const BASE_COUNT = {count};
  const RATE_PER_MS = {rate_per_ms};
  const REFRESH_SEC = {refresh_interval};
  const START_TIME = Date.now();
  const SPARK_DATA = {spark_data};
  const SPARK_LABELS = {spark_labels};

  const countEl = document.getElementById('live-count');
  const progressEl = document.getElementById('progress-fill');
  const refreshTextEl = document.getElementById('refresh-text');

  let lastInt = BASE_COUNT;

  function fmt(n) {{
    return Math.round(n).toLocaleString('ko-KR');
  }}

  function tick() {{
    const elapsed = Date.now() - START_TIME;
    const current = BASE_COUNT + RATE_PER_MS * elapsed;
    const rounded = Math.round(current);

    if (rounded !== lastInt) {{
      countEl.classList.remove('flashing');
      void countEl.offsetWidth;
      countEl.classList.add('flashing');
      lastInt = rounded;
    }}
    countEl.textContent = fmt(rounded);

    const pct = Math.min((elapsed / 1000 / REFRESH_SEC) * 100, 100);
    progressEl.style.width = pct + '%';

    const rem = Math.max(0, REFRESH_SEC - Math.floor(elapsed / 1000));
    const m = Math.floor(rem / 60);
    const s = rem % 60;
    refreshTextEl.textContent = m > 0
      ? `API 갱신까지 ${{m}}분 ${{s < 10 ? '0'+s : s}}초`
      : `API 갱신까지 ${{s}}초`;
  }}

  setInterval(tick, 100);
  tick();
  setTimeout(() => location.reload(), REFRESH_SEC * 1000);

  if (SPARK_DATA.length >= 2) {{
    const section = document.getElementById('spark-section');
    section.style.display = 'block';

    const canvas = document.getElementById('spark');
    const labelsEl = document.getElementById('spark-labels');
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth || 460;
    const H = 80;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const min = Math.min(...SPARK_DATA);
    const max = Math.max(...SPARK_DATA);
    const range = max - min || 1;
    const pad = 8;

    const pts = SPARK_DATA.map((v, i) => {{
      const x = pad + (i / (SPARK_DATA.length - 1)) * (W - pad * 2);
      const y = H - pad - ((v - min) / range) * (H - pad * 2);
      return [x, y];
    }});

    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, 'rgba(225,48,108,0.4)');
    grad.addColorStop(1, 'rgba(225,48,108,0)');

    ctx.beginPath();
    ctx.moveTo(pts[0][0], H);
    ctx.lineTo(pts[0][0], pts[0][1]);
    pts.slice(1).forEach(([x, y]) => ctx.lineTo(x, y));
    ctx.lineTo(pts[pts.length-1][0], H);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    pts.slice(1).forEach(([x, y]) => ctx.lineTo(x, y));
    ctx.strokeStyle = '#E1306C';
    ctx.lineWidth = 2;
    ctx.stroke();

    const [lx, ly] = pts[pts.length - 1];
    ctx.beginPath();
    ctx.arc(lx, ly, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#E1306C';
    ctx.fill();

    if (SPARK_LABELS.length >= 2) {{
      labelsEl.innerHTML =
        `<span>${{SPARK_LABELS[0]}}</span><span>${{SPARK_LABELS[SPARK_LABELS.length-1]}}</span>`;
    }}
  }}
</script>
</body>
</html>"""

    components.html(html, height=620, scrolling=False)


def main():
    cfg = load_config()
    target_username = cfg["targets"][0]["username"]
    target_label = cfg["targets"][0]["label"]
    refresh_interval = cfg.get("poll_interval_seconds", 300)

    st.set_page_config(
        page_title=f"{target_label} 팔로워 라이브",
        page_icon="📡",
        layout="centered",
    )

    st.markdown("""
    <style>
    .stApp { background: #0d0d0d !important; }
    header[data-testid="stHeader"] { display: none !important; }
    footer { display: none !important; }
    .block-container { padding-top: 0 !important; padding-bottom: 0 !important; max-width: 600px !important; }
    div[data-testid="stSpinner"] { color: #E1306C; }
    </style>
    """, unsafe_allow_html=True)

    with st.spinner(""):
        try:
            profile = fetch_profile(target_username)
        except Exception as e:
            st.error(f"오류: {e}")
            time.sleep(30)
            st.rerun()
            return

    # 스냅샷 저장 (클라우드에서는 재시작 시 초기화됨)
    try:
        save_snapshot(target_username, profile["follower_count"])
    except Exception:
        pass

    yesterday_count = get_yesterday_count(target_username)
    trend = load_recent_snapshots(target_username, days=7)

    render_live_counter(profile, yesterday_count, trend, refresh_interval)


if __name__ == "__main__":
    main()
