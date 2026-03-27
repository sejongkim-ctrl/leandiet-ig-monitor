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
import altair as alt
import pandas as pd

from ig_graph_api import fetch_profile, refresh_long_lived_token, load_env

# ── 경로 설정 ─────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = ASSETS_DIR / "data"
CONFIG_FILE = ASSETS_DIR / "config.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_CACHE_FILE = ASSETS_DIR / "token_cache.json"


def get_token_expiry() -> tuple[str | None, int | None]:
    """(만료일 YYYY-MM-DD, 남은 일수) 반환."""
    # 1순위: Streamlit Secrets의 IG_TOKEN_EXPIRES_AT
    try:
        val = st.secrets.get("IG_TOKEN_EXPIRES_AT", "")
        if val:
            d = datetime.strptime(val, "%Y-%m-%d")
            return val, (d - datetime.now()).days
    except Exception:
        pass
    # 2순위: 로컬 token_cache.json
    if TOKEN_CACHE_FILE.exists():
        try:
            cache = json.loads(TOKEN_CACHE_FILE.read_text())
            refreshed_at = datetime.fromisoformat(cache["refreshed_at"])
            expires_in = cache.get("expires_in_seconds", 5184000)
            expires_at = refreshed_at + timedelta(seconds=expires_in)
            return expires_at.strftime("%Y-%m-%d"), (expires_at - datetime.now()).days
        except Exception:
            pass
    return None, None


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


def load_all_snapshots(target: str, days: int = 90) -> list[dict]:
    """전체 스냅샷 로드 + diff 데이터 파싱. 날짜순 정렬."""
    files = sorted(DATA_DIR.glob(f"{target}_*.json"))
    result = []
    for f in files:
        try:
            snap = json.loads(f.read_text())
            date_str = snap.get("date", f.stem.split("_")[-1])
            count = snap.get("follower_count", 0)
            diff = snap.get("diff", {})
            result.append({
                "date": date_str,
                "count": count,
                "new_count": diff.get("new_count"),
                "lost_count": diff.get("lost_count"),
                "net_change": diff.get("net_change"),
                "change_pct": diff.get("change_pct"),
            })
        except Exception:
            continue

    result.sort(key=lambda x: x["date"])

    # diff 없는 구간은 count 차로 net_change 계산
    for i in range(1, len(result)):
        if result[i]["net_change"] is None:
            result[i]["net_change"] = result[i]["count"] - result[i - 1]["count"]

    if days and len(result) > days:
        result = result[-days:]

    return result


def render_dashboard(snapshots: list[dict]) -> None:
    """일별 팔로워 증감 대시보드 섹션."""
    if len(snapshots) < 2:
        st.markdown("""
        <div style="text-align:center; color:#444; font-size:13px; padding:40px 0; letter-spacing:1px;">
            데이터가 쌓이면 추이 차트가 표시됩니다<br>
            <span style="font-size:11px; color:#333;">내일부터 일별 증감을 확인할 수 있습니다</span>
        </div>
        """, unsafe_allow_html=True)
        return

    st.markdown("""
    <div style="border-top: 1px solid #1a1a1a; margin: 20px 0 24px; padding-top: 24px;
                text-align:center; font-size:10px; color:#333; letter-spacing:3px; text-transform:uppercase;">
        일별 팔로워 증감
    </div>
    """, unsafe_allow_html=True)

    # 기간 선택
    period_options = ["7일", "14일", "30일", "전체"]
    period_map = {"7일": 7, "14일": 14, "30일": 30, "전체": len(snapshots)}
    default_period = "전체" if len(snapshots) < 8 else "7일"
    selected = st.segmented_control(
        "기간", period_options, default=default_period, label_visibility="collapsed"
    )
    n = period_map.get(selected, len(snapshots))
    data = snapshots[-n:] if n < len(snapshots) else snapshots

    df = pd.DataFrame(data)
    df["date_label"] = df["date"].str[5:]

    # 요약 메트릭
    valid_changes = [r["net_change"] for r in data if r["net_change"] is not None]
    total_change = sum(valid_changes) if valid_changes else 0
    avg_change = round(total_change / len(valid_changes), 1) if valid_changes else 0
    best_day = max(data, key=lambda x: x["net_change"] if x["net_change"] is not None else float("-inf"))
    best_label = f"{best_day['date'][5:]}  +{best_day['net_change']:,}" if best_day.get("net_change") else "—"

    col1, col2, col3 = st.columns(3)
    sign = "+" if total_change >= 0 else ""
    with col1:
        st.metric("기간 총 증감", f"{sign}{total_change:,}명")
    with col2:
        sign2 = "+" if avg_change >= 0 else ""
        st.metric("일평균 증감", f"{sign2}{avg_change:,}명")
    with col3:
        st.metric("최대 증감일", best_label)

    # 추이 라인+영역 차트
    if len(df) >= 2:
        line_chart = (
            alt.Chart(df)
            .mark_area(
                line={"color": "#E1306C", "strokeWidth": 2},
                color=alt.Gradient(
                    gradient="linear",
                    stops=[
                        alt.GradientStop(color="rgba(225,48,108,0.3)", offset=0),
                        alt.GradientStop(color="rgba(225,48,108,0)", offset=1),
                    ],
                    x1=1, x2=1, y1=1, y2=0,
                ),
            )
            .encode(
                x=alt.X("date:O", axis=alt.Axis(labelColor="#555", tickColor="#1a1a1a", domainColor="#1a1a1a", title=None)),
                y=alt.Y("count:Q", axis=alt.Axis(labelColor="#555", gridColor="#1a1a1a", title=None), scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("date:O", title="날짜"), alt.Tooltip("count:Q", title="팔로워", format=",")],
            )
            .properties(height=160)
            .configure_view(strokeWidth=0, fill="#0d0d0d")
            .configure_axis(labelFontSize=10)
        )
        st.altair_chart(line_chart, use_container_width=True)

    # 증감 바 차트
    bar_df = df[df["net_change"].notna()].copy()
    if len(bar_df) >= 1:
        has_detail = bar_df["new_count"].notna().any()
        if has_detail:
            melt_rows = []
            for _, row in bar_df.iterrows():
                if row["new_count"] is not None:
                    melt_rows.append({"date_label": row["date_label"], "value": row["new_count"], "type": "신규"})
                    melt_rows.append({"date_label": row["date_label"], "value": -row["lost_count"], "type": "이탈"})
            if melt_rows:
                melt_df = pd.DataFrame(melt_rows)
                bar_chart = (
                    alt.Chart(melt_df)
                    .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
                    .encode(
                        x=alt.X("date_label:O", axis=alt.Axis(labelColor="#555", tickColor="#1a1a1a", domainColor="#1a1a1a", title=None)),
                        y=alt.Y("value:Q", axis=alt.Axis(labelColor="#555", gridColor="#1a1a1a", title=None)),
                        color=alt.Color("type:N", scale=alt.Scale(domain=["신규", "이탈"], range=["#2ecc71", "#e74c3c"]), legend=alt.Legend(labelColor="#888", titleColor="#555")),
                        tooltip=[alt.Tooltip("date_label:O", title="날짜"), alt.Tooltip("type:N", title="구분"), alt.Tooltip("value:Q", title="수", format="+,")],
                    )
                    .properties(height=140)
                    .configure_view(strokeWidth=0, fill="#0d0d0d")
                    .configure_axis(labelFontSize=10)
                )
                st.altair_chart(bar_chart, use_container_width=True)
        else:
            bar_df = bar_df.copy()
            bar_df["color"] = bar_df["net_change"].apply(lambda x: "#2ecc71" if x >= 0 else "#e74c3c")
            bar_chart = (
                alt.Chart(bar_df)
                .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
                .encode(
                    x=alt.X("date_label:O", axis=alt.Axis(labelColor="#555", tickColor="#1a1a1a", domainColor="#1a1a1a", title=None)),
                    y=alt.Y("net_change:Q", axis=alt.Axis(labelColor="#555", gridColor="#1a1a1a", title=None)),
                    color=alt.Color("color:N", scale=None, legend=None),
                    tooltip=[alt.Tooltip("date_label:O", title="날짜"), alt.Tooltip("net_change:Q", title="순증감", format="+,")],
                )
                .properties(height=140)
                .configure_view(strokeWidth=0, fill="#0d0d0d")
                .configure_axis(labelFontSize=10)
            )
            st.altair_chart(bar_chart, use_container_width=True)

    # 데이터 테이블
    table_data = []
    for row in reversed(data):
        nc = row["net_change"]
        new_c = row["new_count"]
        lost_c = row["lost_count"]
        table_data.append({
            "날짜": row["date"][5:],
            "팔로워": f"{row['count']:,}",
            "신규": f"+{int(new_c):,}" if new_c is not None else "—",
            "이탈": f"-{int(lost_c):,}" if lost_c is not None else "—",
            "순증감": f"{'+' if nc >= 0 else ''}{int(nc):,}" if nc is not None else "—",
        })
    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)


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
    .block-container { padding-top: 0 !important; padding-bottom: 0 !important; max-width: 720px !important; }
    div[data-testid="stSpinner"] { color: #E1306C; }
    div[data-testid="stMetric"] { background: #111 !important; border-radius: 8px; padding: 12px 16px !important; }
    div[data-testid="stMetricValue"] { color: #fff !important; font-size: 18px !important; }
    div[data-testid="stMetricLabel"] { color: #555 !important; font-size: 11px !important; letter-spacing: 1px; }
    div[data-testid="stDataFrame"] { background: #111 !important; }
    div[data-testid="stSegmentedControl"] button { background: #111 !important; color: #555 !important; border: 1px solid #1a1a1a !important; }
    div[data-testid="stSegmentedControl"] button[aria-checked="true"] { background: #222 !important; color: #fff !important; }
    canvas { background: #0d0d0d !important; }
    </style>
    """, unsafe_allow_html=True)

    # ── 사이드바: 토큰 관리 ──────────────────────────────────────
    with st.sidebar:
        st.markdown("### 토큰 관리")
        expires_at, days_left = get_token_expiry()

        if expires_at and days_left is not None:
            if days_left < 14:
                st.error(f"만료 임박\n\n`{expires_at}`\n\nD-**{days_left}**일")
            elif days_left < 30:
                st.warning(f"만료 예정\n\n`{expires_at}`\n\nD-{days_left}일")
            else:
                st.success(f"정상\n\n`{expires_at}`\n\nD-{days_left}일")
        else:
            st.info("만료일 미설정\n\nSecrets에 `IG_TOKEN_EXPIRES_AT` 추가 시 표시됩니다.")

        st.markdown("---")

        if st.button("토큰 갱신", type="primary", use_container_width=True):
            with st.spinner("Instagram API 갱신 중..."):
                try:
                    env = load_env()
                    current_token = env.get("IG_ACCESS_TOKEN", "")
                    if not current_token:
                        st.error("현재 토큰 없음. Secrets의 IG_ACCESS_TOKEN을 확인하세요.")
                    else:
                        new_token = refresh_long_lived_token(current_token)
                        new_expiry = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
                        st.success(f"갱신 완료! 새 만료일: {new_expiry}")
                        st.markdown("**① 새 토큰 복사:**")
                        st.code(new_token, language=None)
                        st.markdown("**② Streamlit Cloud → Settings → Secrets 에서 교체:**")
                        st.code(
                            f'IG_ACCESS_TOKEN = "{new_token}"\n'
                            f'IG_TOKEN_EXPIRES_AT = "{new_expiry}"',
                            language="toml",
                        )
                except Exception as e:
                    st.error(f"갱신 실패: {e}")

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

    snapshots = load_all_snapshots(target_username, days=90)
    render_dashboard(snapshots)


if __name__ == "__main__":
    main()
