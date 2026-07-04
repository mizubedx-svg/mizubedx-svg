"""
external_data.py
=================
気象庁（注意報・警報）および多摩川の河川データの取得・キャッシュ・
危険度判定・Gemini APIによるAIサマリー生成をまとめたモジュール。

【本モジュールが使用するデータソースは、すべて "スクレイピング禁止" 方針に準拠しています】
HTMLページの解析・自動ブラウジング等は一切行わず、以下の公式・公開API/JSONのみを利用します。

■ ① 気象庁（自動取得・公式）
  気象庁が開発者向けに公開している防災情報JSONデータを直接取得します。
  URL: https://www.jma.go.jp/bosai/warning/data/warning/{都道府県コード}.json
  東京都 = 130000 / 世田谷区（二次細分区域）= 1311200
  これは気象庁が自身のサイトを構築するために公開している構造化JSONデータであり、
  HTMLページを解析するスクレイピングではありません。

■ ② 河川データ（自動取得・公式・無料・無認証）
  国交省「川の防災情報」サイト自体は、利用規約で
  「ツール等による定期的なデータ収集（自動アクセス）はサーバ負担のためお控えください」
  と明記しているため、そこからの自動取得（スクレイピング含む）は一切行いません。

  代わりに Open-Meteo の Flood API（GloFAS: Global Flood Awareness System による
  河川流量シミュレーションの公式REST/JSON API、認証不要・商用利用も無料）を使用します。
  URL: https://flood-api.open-meteo.com/v1/flood?latitude=..&longitude=..&daily=river_discharge

  【重要な注意】
  Open-Meteo Flood APIが返すのは「河川流量シミュレーション値（m3/s、GloFASモデル推定）」であり、
  国交省・二子橋水位観測所が実測する「水位（m）」とは異なる指標です。
  同じ数値軸として扱わず、DB上も別カラムで保持し、あくまで「補助的な参考指標」として扱います。

  現場運用上どうしても「実測水位（m）」が必要な場合は、以下のいずれかを推奨します。
    a) 国交省の正規有料サービス「水防災オープンデータ提供サービス」に契約し、
       そこで発行されたAPIエンドポイントを RIVER_LEVEL_API_URL に設定する
       （契約情報: https://www.river.or.jp/koeki/opendata/index.html）
    b) 契約するまでの間は、スタッフが公式サイトを目視確認して手動入力する
       （river_level_manual_entry テーブル。/admin/river_level で入力）

■ ③ Gemini API（任意・要約生成）
  GEMINI_API_KEY が設定されている場合のみ、上記の公式データを踏まえた
  一言サマリーの強化文を生成します（未設定時は何もしません）。
"""

import json
import os
from datetime import datetime, timedelta

import requests

# ------------------------------------------------------------------
# 設定（環境変数で上書き可能）
# ------------------------------------------------------------------

# --- 気象庁 ---
JMA_AREA_CODE_PREF = os.environ.get("JMA_AREA_CODE_PREF", "130000")     # 東京都
JMA_AREA_CODE_CITY = os.environ.get("JMA_AREA_CODE_CITY", "1311200")    # 世田谷区
JMA_WARNING_URL = f"https://www.jma.go.jp/bosai/warning/data/warning/{JMA_AREA_CODE_PREF}.json"

# --- Open-Meteo Flood API（河川流量シミュレーション。認証不要・スクレイピングではない公式JSON API）---
OPEN_METEO_FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
# 二子玉川（多摩川・二子橋付近）の緯度経度。必要に応じて環境変数で微調整してください。
FUTAKO_LAT = float(os.environ.get("FUTAKO_LAT", "35.6089"))
FUTAKO_LON = float(os.environ.get("FUTAKO_LON", "139.6236"))

# --- 実測水位（国交省・正規契約API or 手動入力によるフォールバック）---
RIVER_LEVEL_API_URL = os.environ.get("RIVER_LEVEL_API_URL")   # 契約済みAPIがあればここに設定
RIVER_LEVEL_API_KEY = os.environ.get("RIVER_LEVEL_API_KEY")

# 危険水位の閾値[m]（多摩川・二子橋付近の氾濫危険水位相当。必ず国交省公表値で調整してください）
RIVER_DANGER_LEVEL_M = float(os.environ.get("RIVER_DANGER_LEVEL_M", "3.8"))
RIVER_CAUTION_LEVEL_M = float(os.environ.get("RIVER_CAUTION_LEVEL_M", "2.5"))

# キャッシュ有効期限（この間は再取得せずキャッシュを返す＝外部サーバへの過度な負荷を避ける）
CACHE_TTL = timedelta(minutes=int(os.environ.get("EXTERNAL_STATUS_CACHE_MINUTES", "10")))

# 危険度を引き上げる警報キーワード
DANGER_WARNING_KEYWORDS = ["特別警報", "氾濫危険", "氾濫発生", "大雨警報", "洪水警報"]
CAUTION_WARNING_KEYWORDS = ["大雨注意報", "洪水注意報", "氾濫注意"]

# 気象庁 warningCode → 日本語名（主要なもののみ。全一覧は気象庁の定義ファイル参照）
JMA_WARNING_CODE_MAP = {
    "02": "暴風警報", "03": "大雨警報", "04": "洪水警報", "05": "暴風雪警報", "06": "大雪警報",
    "07": "波浪警報", "08": "高潮警報", "10": "大雨注意報", "12": "大雪注意報", "13": "風雪注意報",
    "14": "雷注意報", "15": "強風注意報", "16": "波浪注意報", "17": "融雪注意報", "18": "洪水注意報",
    "19": "高潮注意報", "20": "濃霧注意報", "21": "乾燥注意報", "22": "なだれ注意報", "23": "低温注意報",
    "24": "霜注意報", "25": "着氷注意報", "26": "着雪注意報", "32": "暴風特別警報", "33": "大雨特別警報",
    "35": "暴風雪特別警報", "36": "大雪特別警報", "37": "波浪特別警報", "38": "高潮特別警報",
}


# ------------------------------------------------------------------
# ① 気象庁：注意報・警報（公式JSON、自動取得OK）
# ------------------------------------------------------------------
def fetch_jma_warnings():
    """気象庁の公開JSONから世田谷区の現在の注意報・警報を取得する。
    戻り値: {"report_time": str, "warnings": [str, ...]}
    """
    resp = requests.get(JMA_WARNING_URL, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    report_time = data.get("reportDatetime")
    warnings = []

    for area_type in data.get("areaTypes", []):
        for area in area_type.get("areas", []):
            if area.get("code") != JMA_AREA_CODE_CITY:
                continue
            for w in area.get("warnings", []):
                status = w.get("status")
                code = w.get("code")
                if status in ("解除", None):
                    continue
                name = JMA_WARNING_CODE_MAP.get(code, f"警報コード:{code}")
                warnings.append(name)

    return {"report_time": report_time, "warnings": warnings}


# ------------------------------------------------------------------
# ② 河川データ
#    (a) Open-Meteo Flood API：河川流量シミュレーション（自動取得・公式・無認証）
#    (b) 実測水位：契約APIがあればそちら、無ければ手動入力にフォールバック
# ------------------------------------------------------------------
def fetch_river_discharge_openmeteo():
    """Open-Meteo Flood API から二子玉川付近の河川流量シミュレーション値(m3/s)を取得する。
    戻り値: {"discharge_m3s": float, "date": str} または取得失敗時 None
    """
    params = {
        "latitude": FUTAKO_LAT,
        "longitude": FUTAKO_LON,
        "daily": "river_discharge",
        "forecast_days": 1,
        "past_days": 0,
    }
    resp = requests.get(OPEN_METEO_FLOOD_URL, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    daily = data.get("daily", {})
    values = daily.get("river_discharge", [])
    dates = daily.get("time", [])
    if not values:
        return None
    return {"discharge_m3s": values[0], "date": dates[0] if dates else None}


def fetch_river_level_from_contracted_api():
    """正規契約済みの水位APIから実測水位を取得する（RIVER_LEVEL_API_URL未設定ならNone）。
    国交省「水防災オープンデータ提供サービス」等、正式に契約したエンドポイントを想定。
    """
    if not RIVER_LEVEL_API_URL:
        return None
    headers = {}
    if RIVER_LEVEL_API_KEY:
        headers["Authorization"] = f"Bearer {RIVER_LEVEL_API_KEY}"
    resp = requests.get(RIVER_LEVEL_API_URL, headers=headers, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    # 契約先APIのレスポンス形式に合わせて要調整。ここでは {"level_m": 1.23} 形式を想定。
    level = data.get("level_m")
    return float(level) if level is not None else None


def fetch_river_level_manual(db_conn):
    """スタッフが公式サイトを目視確認して手動入力した最新の実測水位を取得する。"""
    row = db_conn.execute(
        "SELECT level_m, observed_at FROM river_level_manual_entry WHERE id = 1"
    ).fetchone()
    if row is None:
        return None, None
    return row["level_m"], row["observed_at"]


def get_river_level(db_conn):
    """実測水位を取得する。契約APIがあればそれを優先、無ければ手動入力値を返す。
    戻り値: (level_m or None, source('contracted_api'|'manual'|None), observed_at)
    """
    try:
        level = fetch_river_level_from_contracted_api()
        if level is not None:
            return level, "contracted_api", datetime.now().isoformat(timespec="seconds")
    except Exception as e:
        print(f"[external_data] 契約水位API取得失敗: {e}")

    level, observed_at = fetch_river_level_manual(db_conn)
    if level is not None:
        return level, "manual", observed_at

    return None, None, None


# ------------------------------------------------------------------
# 危険度判定
# ------------------------------------------------------------------
def judge_alert_level(warnings, river_level_m):
    """気象警報と実測水位（あれば）から総合的な危険度('normal'/'caution'/'danger')を判定する。
    Open-Meteoの流量シミュレーション値は精度特性上、この判定には使用しない（参考表示のみ）。
    """
    warnings_text = " ".join(warnings)

    if any(k in warnings_text for k in DANGER_WARNING_KEYWORDS):
        return "danger"
    if river_level_m is not None and river_level_m >= RIVER_DANGER_LEVEL_M:
        return "danger"

    if any(k in warnings_text for k in CAUTION_WARNING_KEYWORDS):
        return "caution"
    if river_level_m is not None and river_level_m >= RIVER_CAUTION_LEVEL_M:
        return "caution"

    return "normal"


# ------------------------------------------------------------------
# 統合：キャッシュ付きステータス取得
# ------------------------------------------------------------------
def get_external_status(db_conn, force_refresh=False):
    """外部気象・河川ステータスを取得する。
    CACHE_TTL以内であればキャッシュを返し、外部（気象庁・Open-Meteo）への
    過度なアクセスを避ける。
    """
    row = db_conn.execute(
        "SELECT * FROM external_status_cache WHERE id = 1"
    ).fetchone()

    if row and not force_refresh:
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        if datetime.now() - fetched_at < CACHE_TTL:
            return _row_to_status_dict(row)

    # --- ① 気象庁 ---
    warnings, report_time = [], None
    try:
        jma = fetch_jma_warnings()
        warnings = jma["warnings"]
        report_time = jma["report_time"]
    except Exception as e:
        print(f"[external_data] JMA取得失敗: {e}")

    # --- ② 河川データ（流量シミュレーション＋実測水位） ---
    discharge_m3s, discharge_date = None, None
    try:
        d = fetch_river_discharge_openmeteo()
        if d:
            discharge_m3s, discharge_date = d["discharge_m3s"], d["date"]
    except Exception as e:
        print(f"[external_data] Open-Meteo Flood API取得失敗: {e}")

    river_level, river_source, river_fetched_at = get_river_level(db_conn)
    alert_level = judge_alert_level(warnings, river_level)

    now_iso = datetime.now().isoformat(timespec="seconds")
    db_conn.execute(
        """INSERT INTO external_status_cache
           (id, fetched_at, jma_area_code, jma_warnings_json, jma_report_time,
            river_level_m, river_level_source, river_level_fetched_at,
            river_discharge_m3s, river_discharge_date, alert_level)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             fetched_at=excluded.fetched_at,
             jma_area_code=excluded.jma_area_code,
             jma_warnings_json=excluded.jma_warnings_json,
             jma_report_time=excluded.jma_report_time,
             river_level_m=excluded.river_level_m,
             river_level_source=excluded.river_level_source,
             river_level_fetched_at=excluded.river_level_fetched_at,
             river_discharge_m3s=excluded.river_discharge_m3s,
             river_discharge_date=excluded.river_discharge_date,
             alert_level=excluded.alert_level
        """,
        (
            now_iso, JMA_AREA_CODE_CITY, json.dumps(warnings, ensure_ascii=False),
            report_time, river_level, river_source, river_fetched_at,
            discharge_m3s, discharge_date, alert_level,
        ),
    )

    if alert_level == "danger":
        db_conn.execute(
            "INSERT INTO alert_log (reason, river_level_m, warnings_json) VALUES (?, ?, ?)",
            (f"危険度danger判定（実測水位={river_level}）", river_level, json.dumps(warnings, ensure_ascii=False)),
        )
    db_conn.commit()

    return {
        "fetched_at": now_iso,
        "jma_report_time": report_time,
        "warnings": warnings,
        "river_level_m": river_level,
        "river_level_source": river_source,
        "river_level_fetched_at": river_fetched_at,
        "river_discharge_m3s": discharge_m3s,
        "river_discharge_date": discharge_date,
        "alert_level": alert_level,
    }


def _row_to_status_dict(row):
    return {
        "fetched_at": row["fetched_at"],
        "jma_report_time": row["jma_report_time"],
        "warnings": json.loads(row["jma_warnings_json"]) if row["jma_warnings_json"] else [],
        "river_level_m": row["river_level_m"],
        "river_level_source": row["river_level_source"],
        "river_level_fetched_at": row["river_level_fetched_at"],
        "river_discharge_m3s": row["river_discharge_m3s"],
        "river_discharge_date": row["river_discharge_date"],
        "alert_level": row["alert_level"],
    }


def save_manual_river_level(db_conn, level_m, observed_at, entered_by):
    """スタッフによる実測水位の手動入力を保存する（契約API未契約時のフォールバック用）。"""
    db_conn.execute(
        """INSERT INTO river_level_manual_entry (id, level_m, observed_at, entered_by)
           VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             level_m=excluded.level_m,
             observed_at=excluded.observed_at,
             entered_by=excluded.entered_by,
             created_at=datetime('now','localtime')
        """,
        (level_m, observed_at, entered_by),
    )
    db_conn.commit()


# ------------------------------------------------------------------
# ③ Gemini API によるAIサマリー生成（任意機能／GEMINI_API_KEY未設定なら無効）
# ------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)


def generate_ai_summary(area, form_values, external_status, staff_summary=""):
    """公的気象データ＋河川データ＋現地観測値をもとに、一言サマリーの精度を強化した
    AI要約を生成する。GEMINI_API_KEY未設定、またはAPI呼び出し失敗時は None を返す。
    """
    if not GEMINI_API_KEY:
        return None

    warnings = external_status.get("warnings") or []
    warnings_text = "、".join(warnings) if warnings else "発令なし"

    river_level = external_status.get("river_level_m")
    if river_level is not None:
        source_label = "契約API実測" if external_status.get("river_level_source") == "contracted_api" else "スタッフ手動確認"
        river_text = f"{river_level}m（{source_label}）"
    else:
        river_text = "実測水位データなし"

    discharge = external_status.get("river_discharge_m3s")
    discharge_text = f"{discharge}m3/s（GloFASシミュレーション参考値）" if discharge is not None else "データなし"

    prompt = f"""あなたは水辺の安全観測レポートを要約する担当者です。
以下の現地観測データと公的気象・河川データをもとに、水辺の安全担当者向けに
状況を50文字程度で簡潔に要約してください。誇張せず、事実ベースで記述してください。
シミュレーション参考値と実測値は区別して扱ってください。

【エリア】{area}
【現地観測データ】{json.dumps(form_values, ensure_ascii=False)}
【スタッフによる一言メモ】{staff_summary or "(記入なし)"}
【気象庁 発令中の警報・注意報】{warnings_text}
【多摩川・実測水位（二子橋付近）】{river_text}
【多摩川・河川流量シミュレーション参考値】{discharge_text}

出力は要約文のみとし、前置きや箇条書き記号は不要です。"""

    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return text.strip()
    except Exception as e:
        print(f"[external_data] Gemini要約生成失敗: {e}")
        return None
