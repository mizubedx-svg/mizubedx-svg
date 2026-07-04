import json
import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

from flask import Flask, g, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename

import external_data
import report_generator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "water_risk.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "heic"}
MAX_CONTENT_LENGTH = 12 * 1024 * 1024  # 12MB (フォーム上限10MB + 余裕)

# エリアごとのテーブル／カラム対応（ダッシュボード一覧・PDFレポート生成で共用）
AREA_CONFIG = {
    "二子玉川バーベキュー場": {
        "table": "obs_bbq",
        "score_labels": {
            "time_slot": "時間帯", "weather": "天候", "rain_recent": "前日〜当日の雨",
            "upstream_impact": "上流の影響", "water_level": "水位 (0-3)",
            "flow_speed": "流速 (0-3)", "turbidity": "濁り (0-3)",
            "crowd_level": "人の多さ (0-3)", "water_edge_approach": "水際接近 (0-3)",
            "density_level": "滞留密度 (0-3)", "alcohol_level": "飲酒レベル (0-3)",
        },
    },
    "兵庫島公園1": {
        "table": "obs_hyogojima1",
        "score_labels": {
            "time_slot": "時間帯", "weather": "天候", "rain_recent": "前日〜当日の雨",
            "upstream_impact": "上流の影響", "water_level": "水位 (0-3)",
            "flow_speed": "流速 (0-3)", "turbidity": "濁り (0-3)",
            "crowd_level": "人の多さ (0-3)", "water_edge_approach": "水際接近 (0-3)",
            "density_level": "滞留密度 (0-3)", "guardian_supervision": "保護者の監視レベル (0-2)",
        },
    },
    "兵庫島公園2（多摩川側）": {
        "table": "obs_hyogojima2",
        "score_labels": {
            "weather": "天候", "water_level": "水位 (0-3)", "flow_speed": "流速 (0-3)",
            "turbidity": "濁り (0-3)", "crowd_level": "人の多さ (0-3)",
            "water_edge_approach": "水際接近 (0-3)", "density_level": "滞留密度 (0-3)",
            "opposite_bank_impact": "対岸の状況影響 (0-3)",
        },
    },
}

# ==========================================
# 🔑 管理者用の認証設定（ここを自由に変更してください）
# ==========================================
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mizubedx2026") # 👈仮のパスワードです

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
os.makedirs(UPLOAD_DIR, exist_ok=True)


def check_auth(username, password):
    """ユーザー名とパスワードが正しいかチェックする関数"""
    return username == ADMIN_USER and password == ADMIN_PASSWORD


def requires_auth(f):
    """管理画面のルート（URL）に鍵をかけるためのデコレータ関数"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "認証が必要です。正しいユーザー名とパスワードを入力してください。",
                401,
                {"WWW-Authenticate": 'Basic realm="Login Required"'}
            )
        return f(*args, **kwargs)
    return decorated


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            conn.executescript(f.read())


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_photo(file_storage, prefix):
    """写真を保存してパス（static/uploads/配下の相対パス）を返す。未添付ならNone。"""
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        raise ValueError("対応していないファイル形式です（jpg/jpeg/png/webp/heicのみ）")
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    filename = f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, secure_filename(filename))
    file_storage.save(filepath)
    return f"uploads/{secure_filename(filename)}"


def get_multi(form, name):
    """checkbox（複数選択）の値をカンマ区切り文字列にして返す"""
    values = form.getlist(name)
    return ",".join(values) if values else None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """現在の気象庁警報・多摩川水位・危険度を返す。
    フォームを開いた瞬間にフロントから呼ばれる想定（キャッシュTTL内は再取得しない）。
    """
    db = get_db()
    status = external_data.get_external_status(db)
    
    # 🔒 【安全装置】画面の「None発令中」を綺麗な日本語に修正
    if status and isinstance(status, dict):
        warnings = status.get("warnings")
        if not warnings or warnings == "None" or warnings == ["None"]:
            status["warnings"] = ["なし（現在、発令中の警報はありません）"]
            
    return jsonify(status)


@app.route("/admin/river_level", methods=["POST"])
@requires_auth  # 🔒 ロックを追加
def admin_river_level():
    """水位の正規自動連携が未契約の場合の、スタッフによる手動入力バックアップ。
    現場スタッフが国交省「川の防災情報」を目視確認し、数値を入力する運用を想定。
    """
    data = request.get_json(silent=True) or request.form
    try:
        level_m = float(data.get("level_m"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "level_m は数値で指定してください"}), 400

    observed_at = data.get("observed_at") or datetime.now().isoformat(timespec="seconds")
    entered_by = data.get("entered_by", "")

    db = get_db()
    external_data.save_manual_river_level(db, level_m, observed_at, entered_by)
    # 手動入力後は即座に再判定してキャッシュを更新
    status = external_data.get_external_status(db, force_refresh=True)
    return jsonify({"ok": True, "status": status})


@app.route("/submit", methods=["POST"])
def submit():
    form = request.form
    files = request.files

    area = form.get("area")
    if area not in ("二子玉川バーベキュー場", "兵庫島公園1", "兵庫島公園2（多摩川側）"):
        return jsonify({"ok": False, "error": "観測エリアが不正です"}), 400

    required_common = ["observation_date", "observation_time", "observer_id"]
    for key in required_common:
        if not form.get(key):
            return jsonify({"ok": False, "error": f"{key} は必須です"}), 400

    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO observations
               (observation_date, observation_time, observer_id, area)
               VALUES (?, ?, ?, ?)""",
            (
                form.get("observation_date"),
                form.get("observation_time"),
                form.get("observer_id"),
                area,
            ),
        )
        obs_id = cur.lastrowid

        # 公的気象データ（キャッシュ済みならAPIを叩かず即返る）を取得し、
        # Gemini APIへのプロンプトに「大雨注意報発令中、水位〇m」のように組み込む
        external_status = external_data.get_external_status(db)

        if area == "二子玉川バーベキュー場":
            photo_path = save_photo(files.get("bbq_photo"), "bbq")
            bbq_values = {
                "時間帯": form.get("bbq_time_slot"), "天候": form.get("bbq_weather"),
                "前日〜当日の雨": form.get("bbq_rain_recent"), "上流の影響": form.get("bbq_upstream_impact"),
                "水位": form.get("bbq_water_level"), "流速": form.get("bbq_flow_speed"),
                "濁り": form.get("bbq_turbidity"), "人の多さ": form.get("bbq_crowd_level"),
                "水際接近": form.get("bbq_water_edge_approach"), "滞留密度": form.get("bbq_density_level"),
                "飲酒レベル": form.get("bbq_alcohol_level"), "危険フラグ": get_multi(form, "bbq_danger_flags"),
            }
            ai_summary = external_data.generate_ai_summary(
                area, bbq_values, external_status, form.get("bbq_summary")
            )
            db.execute(
                """INSERT INTO obs_bbq (
                    observation_id, time_slot, weather, rain_recent, upstream_impact,
                    water_level, flow_speed, turbidity, crowd_level,
                    water_edge_approach, density_level, alcohol_level,
                    danger_flags, site_memo, event_log, summary, ai_summary, photo_path,
                    weather_warnings_snapshot, river_level_snapshot_m,
                    river_discharge_snapshot_m3s, external_snapshot_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obs_id,
                    form.get("bbq_time_slot"),
                    form.get("bbq_weather"),
                    form.get("bbq_rain_recent"),
                    form.get("bbq_upstream_impact"),
                    form.get("bbq_water_level"),
                    form.get("bbq_flow_speed"),
                    form.get("bbq_turbidity"),
                    form.get("bbq_crowd_level"),
                    form.get("bbq_water_edge_approach"),
                    form.get("bbq_density_level"),
                    form.get("bbq_alcohol_level"),
                    get_multi(form, "bbq_danger_flags"),
                    form.get("bbq_site_memo"),
                    form.get("bbq_event_log"),
                    form.get("bbq_summary"),
                    ai_summary,
                    photo_path,
                    json.dumps(external_status.get("warnings") or [], ensure_ascii=False),
                    external_status.get("river_level_m"),
                    external_status.get("river_discharge_m3s"),
                    external_status.get("fetched_at"),
                ),
            )

        elif area == "兵庫島公園1":
            photo_path = save_photo(files.get("h1_photo"), "hyogojima1")
            h1_values = {
                "時間帯": form.get("h1_time_slot"), "天候": form.get("h1_weather"),
                "前日〜当日の雨": form.get("h1_rain_recent"), "上流の影響": form.get("h1_upstream_impact"),
                "水位": form.get("h1_water_level"), "流速": form.get("h1_flow_speed"),
                "濁り": form.get("h1_turbidity"), "人の多さ": form.get("h1_crowd_level"),
                "水際接近": form.get("h1_water_edge_approach"), "滞留密度": form.get("h1_density_level"),
                "保護者の監視レベル": form.get("h1_guardian_supervision"),
                "危険フラグ": get_multi(form, "h1_danger_flags"),
            }
            ai_summary = external_data.generate_ai_summary(
                area, h1_values, external_status, form.get("h1_summary")
            )
            db.execute(
                """INSERT INTO obs_hyogojima1 (
                    observation_id, time_slot, weather, rain_recent, upstream_impact,
                    water_level, flow_speed, turbidity, crowd_level,
                    water_edge_approach, density_level, guardian_supervision,
                    danger_flags, site_memo, event_log, summary, ai_summary, photo_path,
                    weather_warnings_snapshot, river_level_snapshot_m,
                    river_discharge_snapshot_m3s, external_snapshot_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obs_id,
                    form.get("h1_time_slot"),
                    form.get("h1_weather"),
                    form.get("h1_rain_recent"),
                    form.get("h1_upstream_impact"),
                    form.get("h1_water_level"),
                    form.get("h1_flow_speed"),
                    form.get("h1_turbidity"),
                    form.get("h1_crowd_level"),
                    form.get("h1_water_edge_approach"),
                    form.get("h1_density_level"),
                    form.get("h1_guardian_supervision"),
                    get_multi(form, "h1_danger_flags"),
                    form.get("h1_site_memo"),
                    form.get("h1_event_log"),
                    form.get("h1_summary"),
                    ai_summary,
                    photo_path,
                    json.dumps(external_status.get("warnings") or [], ensure_ascii=False),
                    external_status.get("river_level_m"),
                    external_status.get("river_discharge_m3s"),
                    external_status.get("fetched_at"),
                ),
            )

        else:  # 兵庫島公園2（多摩川側）
            photo_path = save_photo(files.get("h2_photo"), "hyogojima2")
            h2_values = {
                "天候": form.get("h2_weather"), "水位": form.get("h2_water_level"),
                "流速": form.get("h2_flow_speed"), "濁り": form.get("h2_turbidity"),
                "人の多さ": form.get("h2_crowd_level"), "水際接近": form.get("h2_water_edge_approach"),
                "滞留密度": form.get("h2_density_level"),
                "対岸の状況影響": form.get("h2_opposite_bank_impact"),
                "危険フラグ": get_multi(form, "h2_danger_flags"),
            }
            ai_summary = external_data.generate_ai_summary(
                area, h2_values, external_status, form.get("h2_summary")
            )
            db.execute(
                """INSERT INTO obs_hyogojima2 (
                    observation_id, weather, water_level, flow_speed, turbidity,
                    crowd_level, water_edge_approach, density_level,
                    opposite_bank_impact, danger_flags, site_memo, event_log,
                    summary, ai_summary, photo_path,
                    weather_warnings_snapshot, river_level_snapshot_m,
                    river_discharge_snapshot_m3s, external_snapshot_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obs_id,
                    form.get("h2_weather"),
                    form.get("h2_water_level") or None,
                    form.get("h2_flow_speed"),
                    form.get("h2_turbidity"),
                    form.get("h2_crowd_level"),
                    form.get("h2_water_edge_approach") or None,
                    form.get("h2_density_level") or None,
                    form.get("h2_opposite_bank_impact"),
                    get_multi(form, "h2_danger_flags"),
                    form.get("h2_site_memo"),
                    form.get("h2_event_log"),
                    form.get("h2_summary"),
                    ai_summary,
                    photo_path,
                    json.dumps(external_status.get("warnings") or [], ensure_ascii=False),
                    external_status.get("river_level_m"),
                    external_status.get("river_discharge_m3s"),
                    external_status.get("fetched_at"),
                ),
            )

        db.commit()
        return jsonify({"ok": True, "observation_id": obs_id})

    except sqlite3.IntegrityError as e:
        db.rollback()
        return jsonify({"ok": False, "error": f"入力値が不正です: {e}"}), 400
    except ValueError as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400


# ------------------------------------------------------------------
# ダッシュボード（管理画面）
# ------------------------------------------------------------------
@app.route("/dashboard")
@app.route("/dashboard.html")
@requires_auth  # 🔒 ロックを追加
def dashboard():
    return render_template("dashboard.html")


def _fetch_observation_with_area_data(db, observation_id):
    """observations + エリア別テーブルをJOINして1件取得するヘルパー。"""
    obs = db.execute(
        "SELECT * FROM observations WHERE id = ?", (observation_id,)
    ).fetchone()
    if obs is None:
        return None, None, None

    config = AREA_CONFIG.get(obs["area"])
    if config is None:
        return obs, None, None

    area_row = db.execute(
        f"SELECT * FROM {config['table']} WHERE observation_id = ?", (observation_id,)
    ).fetchone()
    return obs, config, area_row


@app.route("/api/observations")
@requires_auth  # 🔒 ロックを追加
def api_observations():
    """ダッシュボード一覧表示用：観測ログ＋一言サマリー（report_summary優先）を返す。"""
    db = get_db()
    observations = db.execute(
        "SELECT * FROM observations ORDER BY id DESC LIMIT 200"
    ).fetchall()

    today_count = db.execute(
        "SELECT COUNT(*) AS c FROM observations WHERE observation_date = date('now','localtime')"
    ).fetchone()["c"]

    results = []
    for obs in observations:
        config = AREA_CONFIG.get(obs["area"])
        area_row = None
        if config:
            area_row = db.execute(
                f"SELECT * FROM {config['table']} WHERE observation_id = ?", (obs["id"],)
            ).fetchone()

        danger_flags = []
        summary_preview = None
        has_photo = False
        if area_row is not None:
            if area_row["danger_flags"]:
                danger_flags = area_row["danger_flags"].split(",")
            # 一言サマリーの優先順位：日次PDF用report_summary → 送信時ai_summary → スタッフ入力summary
            summary_preview = area_row["report_summary"] or area_row["ai_summary"] or area_row["summary"]
            has_photo = bool(area_row["photo_path"])

        results.append({
            "id": obs["id"],
            "observation_date": obs["observation_date"],
            "observation_time": obs["observation_time"],
            "observer_id": obs["observer_id"],
            "area": obs["area"],
            "danger_flags": danger_flags,
            "summary_preview": summary_preview,
            "has_report_summary": bool(area_row and area_row["report_summary"]),
            "has_photo": has_photo,
        })

    return jsonify({"observations": results, "today_count": today_count})


# ------------------------------------------------------------------
# 日次PDFレポート（Gemini要約＋写真埋め込み）
# ------------------------------------------------------------------
@app.route("/api/report/<int:observation_id>/pdf")
@requires_auth  # 🔒 ロックを追加
def api_report_pdf(observation_id):
    """観測データからAI一言サマリー＋写真付きの安全パトロール報告書PDFを生成して返す。
    report_summaryが未生成、または ?refresh=1 が指定された場合のみGemini APIを呼び出す
    （キャッシュにより、閲覧のたびに再生成しない）。
    """
    db = get_db()
    obs, config, area_row = _fetch_observation_with_area_data(db, observation_id)

    if obs is None:
        return jsonify({"ok": False, "error": "指定された観測データが見つかりません"}), 404
    if config is None or area_row is None:
        return jsonify({"ok": False, "error": "観測エリアの詳細データが見つかりません"}), 404

    force_refresh = request.args.get("refresh") == "1"

    score_items = [
        (label, area_row[col]) for col, label in config["score_labels"].items()
    ]
    danger_flags = area_row["danger_flags"].split(",") if area_row["danger_flags"] else []
    site_memo = area_row["site_memo"]
    staff_summary = area_row["summary"]

    # 観測時点の気象・水位データ（スナップショット）。
    # 旧データ等でスナップショットが無い場合は、現在の外部データで代替する
    # （その場合は「観測時点データなし・現在値」であることをPDF上に明記する）。
    if area_row["external_snapshot_at"]:
        weather_context = {
            "warnings": json.loads(area_row["weather_warnings_snapshot"]) if area_row["weather_warnings_snapshot"] else [],
            "river_level_m": area_row["river_level_snapshot_m"],
            "river_discharge_m3s": area_row["river_discharge_snapshot_m3s"],
            "fetched_at": area_row["external_snapshot_at"],
            "is_snapshot": True,
        }
    else:
        live_status = external_data.get_external_status(db)
        weather_context = {
            "warnings": live_status.get("warnings") or [],
            "river_level_m": live_status.get("river_level_m"),
            "river_discharge_m3s": live_status.get("river_discharge_m3s"),
            "fetched_at": live_status.get("fetched_at"),
            "is_snapshot": False,
        }

    report_summary = area_row["report_summary"]
    if not report_summary or force_refresh:
        report_summary = report_generator.generate_report_summary(
            obs["area"], score_items, danger_flags, site_memo, weather_context
        )
        db.execute(
            f"UPDATE {config['table']} SET report_summary = ?, report_generated_at = ? "
            f"WHERE observation_id = ?",
            (report_summary, datetime.now().isoformat(timespec="seconds"), observation_id),
        )
        db.commit()

    photo_data_uri = None
    if area_row["photo_path"]:
        photo_abs_path = os.path.join(BASE_DIR, "static", area_row["photo_path"])
        photo_data_uri = report_generator.resize_photo_to_data_uri(photo_abs_path)

    pdf_bytes = report_generator.render_report_pdf(
        observation=obs,
        score_items=score_items,
        danger_flags=danger_flags,
        site_memo=site_memo,
        staff_summary=staff_summary,
        report_summary=report_summary,
        photo_data_uri=photo_data_uri,
        weather_context=weather_context,
    )

    filename = f"safety_patrol_report_{observation_id}_{obs['observation_date']}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------------------------------------------
# DB初期化
# ------------------------------------------------------------------
init_db()


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    threads = int(os.environ.get("WAITRESS_THREADS", "8"))

    print(f"Waitress WSGIサーバーを起動します: http://{host}:{port} (threads={threads})")
    serve(app, host=host, port=port, threads=threads)
