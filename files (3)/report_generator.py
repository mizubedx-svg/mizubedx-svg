"""
report_generator.py
====================
観測データから、世田谷区役所提出用の「安全パトロール報告書（PDF）」を生成する。

構成:
  1. generate_report_summary() : Gemini API（既定 gemini-2.5-flash）で
     客観的・簡潔な一言サマリー（2-3文、100文字程度）を生成
  2. resize_photo_to_data_uri() : 現場写真をPillowでリサイズし、
     PDFテンプレートに埋め込めるbase64 data URIに変換
  3. render_report_pdf()        : Jinja2テンプレート（templates/report.html）に
     データを流し込み、pdfkit（wkhtmltopdf）でPDF化する

【PDFライブラリについて】
weasyprintはこの実行環境のパッケージインデックスに存在しなかったため、
同じ「HTML/CSSでレイアウトを組む」方針を維持できる pdfkit（+ wkhtmltopdf）を
採用しています。wkhtmltopdfバイナリがシステムにインストールされている必要があります
（Ubuntu/Debianなら `apt-get install -y wkhtmltopdf`）。
weasyprintが導入可能な環境であれば、render_report_pdf() の実装部分を
weasyprint.HTML(string=html).write_pdf() に差し替えるだけで移行できます。
"""

import base64
import io
import os
from datetime import datetime

import pdfkit
import requests
from flask import render_template
from PIL import Image

# ------------------------------------------------------------------
# Gemini API 設定（レポート要約は要件通り gemini-2.5-flash を使用）
# ------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
REPORT_GEMINI_MODEL = os.environ.get("REPORT_GEMINI_MODEL", "gemini-2.5-flash")
REPORT_GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{REPORT_GEMINI_MODEL}:generateContent"
)

# 写真リサイズ設定（PDFに埋め込むサイズを抑えてファイルサイズ・生成時間を軽量化）
PHOTO_MAX_WIDTH = int(os.environ.get("REPORT_PHOTO_MAX_WIDTH", "900"))
PHOTO_JPEG_QUALITY = int(os.environ.get("REPORT_PHOTO_JPEG_QUALITY", "78"))

# pdfkit（wkhtmltopdf）オプション
WKHTMLTOPDF_OPTIONS = {
    "encoding": "UTF-8",
    "quiet": "",
    "enable-local-file-access": "",
}


# ------------------------------------------------------------------
# ① Gemini APIで一言サマリーを生成
# ------------------------------------------------------------------
def generate_report_summary(area, score_items, danger_flags, site_memo, weather_context=None):
    """世田谷区役所への日次報告書にふさわしい、客観的で簡潔な一言サマリーを生成する。
    2-3文・100文字程度。GEMINI_API_KEY未設定時はテンプレート文で代替する。

    weather_context: {"warnings": [...], "river_level_m": float|None,
                       "river_discharge_m3s": float|None, "fetched_at": str, "is_snapshot": bool}
    観測時点（送信時）の気象庁警報・多摩川水位/流量データ。無ければ現在値が渡される想定。
    """
    weather_context = weather_context or {}
    scores_text = "、".join(f"{label}: {value}" for label, value in score_items if value not in (None, ""))
    flags_text = "、".join(danger_flags) if danger_flags else "なし"
    memo_text = site_memo or "（記入なし）"

    warnings = weather_context.get("warnings") or []
    warnings_text = "、".join(warnings) if warnings else "発令なし"
    river_level = weather_context.get("river_level_m")
    river_text = f"{river_level}m（実測）" if river_level is not None else "実測データなし"
    discharge = weather_context.get("river_discharge_m3s")
    discharge_text = f"{discharge}m3/s（GloFASシミュレーション参考値）" if discharge is not None else "データなし"

    if not GEMINI_API_KEY:
        # APIキー未設定時のフォールバック（動作は止めない）
        base = f"{area}における観測結果、危険フラグ: {flags_text}。気象庁発表: {warnings_text}。"
        return (base + "詳細はスコア表を参照してください。")[:150]

    prompt = f"""あなたは世田谷区役所に提出する水辺安全パトロールの日次報告書を作成する担当者です。
以下の観測データと、観測時点の公的気象・河川データをもとに、客観的で簡潔な「一言サマリー」を
2〜3文・100文字程度で作成してください。
断定的な危険評価や誇張表現は避け、観測された事実に基づいて記述してください。
行政向けの文体（である調・敬体は使わず、報告書らしい簡潔な体言止め・常体）にしてください。

【観測エリア】{area}
【リスクスコア】{scores_text or "データなし"}
【危険フラグ】{flags_text}
【現場メモ】{memo_text}
【観測時点の気象庁 警報・注意報】{warnings_text}
【観測時点の多摩川・実測水位】{river_text}
【観測時点の河川流量シミュレーション参考値】{discharge_text}

出力は要約文のみとし、見出しや箇条書き記号、前置きは不要です。"""

    try:
        resp = requests.post(
            f"{REPORT_GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text
    except Exception as e:
        print(f"[report_generator] Gemini要約生成失敗: {e}")
        base = f"{area}における観測結果、危険フラグ: {flags_text}。"
        return (base + "詳細はスコア表を参照してください。（AI要約は生成できませんでした）")[:150]


# ------------------------------------------------------------------
# ② 写真リサイズ → base64 data URI
# ------------------------------------------------------------------
def resize_photo_to_data_uri(photo_abs_path):
    """写真ファイルをリサイズしてJPEGに変換し、PDFに埋め込み可能なdata URIを返す。
    ファイルが存在しない/読めない場合は None を返す（PDF生成自体は継続する）。
    """
    if not photo_abs_path or not os.path.exists(photo_abs_path):
        return None

    try:
        with Image.open(photo_abs_path) as img:
            img = img.convert("RGB")
            if img.width > PHOTO_MAX_WIDTH:
                ratio = PHOTO_MAX_WIDTH / img.width
                img = img.resize((PHOTO_MAX_WIDTH, int(img.height * ratio)))

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=PHOTO_JPEG_QUALITY)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        print(f"[report_generator] 写真リサイズ失敗: {e}")
        return None


# ------------------------------------------------------------------
# ③ PDF生成
# ------------------------------------------------------------------
def render_report_pdf(observation, score_items, danger_flags, site_memo,
                       staff_summary, report_summary, photo_data_uri, weather_context=None):
    """Jinja2テンプレート(templates/report.html)にデータを流し込み、PDFバイト列を返す。"""
    html = render_template(
        "report.html",
        observation=observation,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        score_items=score_items,
        danger_flags=danger_flags,
        site_memo=site_memo,
        staff_summary=staff_summary,
        report_summary=report_summary,
        photo_data_uri=photo_data_uri,
        weather_context=weather_context or {},
    )
    pdf_bytes = pdfkit.from_string(html, False, options=WKHTMLTOPDF_OPTIONS)
    return pdf_bytes
