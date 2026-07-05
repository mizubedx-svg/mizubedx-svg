-- =========================================================
-- 水辺リスク観測（条件分岐版）DBスキーマ
-- Googleフォーム「水辺リスク観測（条件分岐版）」の項目・選択肢・スコアを
-- そのまま反映しています。
-- =========================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------
-- 共通テーブル：セクション1（全エリア共通の設問）
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_date TEXT NOT NULL,                 -- 日付 (YYYY-MM-DD)
    observation_time TEXT NOT NULL,                 -- 時間 (HH:MM)
    observer_id      TEXT NOT NULL,                 -- 観測員ID
    area             TEXT NOT NULL CHECK (area IN (
                          '二子玉川バーベキュー場',
                          '兵庫島公園1',
                          '兵庫島公園2（多摩川側）'
                      )),                            -- 【最重要】観測エリア
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------------------------------------------------------
-- セクション2：【二子玉川BBQ場】観測項目
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS obs_bbq (
    observation_id     INTEGER PRIMARY KEY
                        REFERENCES observations(id) ON DELETE CASCADE,

    time_slot           TEXT NOT NULL CHECK (time_slot IN (
                            '昼ピーク（11:30-14:30）',
                            '夕方ピーク（16:30-18:00）'
                        )),
    weather              TEXT NOT NULL CHECK (weather IN (
                            '晴れ','曇り','小雨','雨','強い雨'
                        )),
    rain_recent          TEXT NOT NULL CHECK (rain_recent IN (
                            'なし','少しあり','あり','多い（増水注意）'
                        )),
    upstream_impact      TEXT NOT NULL CHECK (upstream_impact IN (
                            '影響なし','少し変化あり','変化あり（濁り・流木）','明確な増水兆候'
                        )),
    water_level          INTEGER NOT NULL CHECK (water_level BETWEEN 0 AND 3),   -- 0低い〜3危険（護岸付近まで）
    flow_speed           INTEGER NOT NULL CHECK (flow_speed BETWEEN 0 AND 3),    -- 0緩やか〜3激流
    turbidity            INTEGER NOT NULL CHECK (turbidity BETWEEN 0 AND 3),     -- 0澄んでいる〜3激しい濁り
    crowd_level          INTEGER NOT NULL CHECK (crowd_level BETWEEN 0 AND 3),   -- 人の多さ
    water_edge_approach  INTEGER NOT NULL CHECK (water_edge_approach BETWEEN 0 AND 3), -- 水際接近
    density_level        INTEGER NOT NULL CHECK (density_level BETWEEN 0 AND 3), -- 滞留密度
    alcohol_level        INTEGER NOT NULL CHECK (alcohol_level BETWEEN 0 AND 3), -- 飲酒レベル
    danger_flags         TEXT,      -- 複数選択：子ども単独,飛び込み,流れ急変,岸の崩れ（カンマ区切り）
    site_memo            TEXT,      -- 状況メモ（任意）
    event_log            TEXT,      -- イベント発生（任意）
    summary              TEXT,      -- 一言サマリー（任意、スタッフ入力）
    ai_summary           TEXT,      -- AI生成サマリー（任意、公的気象データを加味して自動生成）
    report_summary        TEXT,     -- 日次PDF報告書用サマリー（Gemini 2.5 Flash生成・キャッシュ）
    report_generated_at   TEXT,     -- report_summaryの生成日時
    weather_warnings_snapshot   TEXT,     -- 送信時点の気象庁警報・注意報スナップショット（JSON文字列）
    river_level_snapshot_m      REAL,     -- 送信時点の実測水位[m]スナップショット（あれば）
    river_discharge_snapshot_m3s REAL,     -- 送信時点のOpen-Meteo流量シミュレーション参考値[m3/s]スナップショット
    external_snapshot_at         TEXT,     -- 上記スナップショットの取得時刻
    temperature_snapshot_c      REAL,     -- 送信時点の気温[℃]スナップショット
    humidity_snapshot_pct       REAL,     -- 送信時点の湿度[%]スナップショット
    photo_path            TEXT       -- 現場の写真（本流・水際・空のみ）
);

-- ---------------------------------------------------------
-- セクション3：【兵庫島公園1】観測項目
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS obs_hyogojima1 (
    observation_id     INTEGER PRIMARY KEY
                        REFERENCES observations(id) ON DELETE CASCADE,

    time_slot            TEXT NOT NULL CHECK (time_slot IN (
                            '昼ピーク（11:30-14:30）',
                            '夕方ピーク（16:30-18:00）'
                        )),
    weather              TEXT NOT NULL CHECK (weather IN (
                            '晴れ','曇り','小雨','雨','強い雨'
                        )),
    rain_recent          TEXT NOT NULL CHECK (rain_recent IN (
                            'なし','少しあり','あり','多い（増水注意）'
                        )),
    upstream_impact      TEXT NOT NULL CHECK (upstream_impact IN (
                            '影響なし','少し変化あり','変化あり（水路の増水）','明確な増水兆候'
                        )),                                                       -- 上流の影響（野川・合流部）
    water_level          INTEGER NOT NULL CHECK (water_level BETWEEN 0 AND 3),    -- 水位（人工水路・ひょうたん池）
    flow_speed           INTEGER NOT NULL CHECK (flow_speed BETWEEN 0 AND 3),     -- 流速（野川・合流部手前）
    turbidity            INTEGER NOT NULL CHECK (turbidity BETWEEN 0 AND 3),      -- 濁り（野川・合流部手前）
    crowd_level          INTEGER NOT NULL CHECK (crowd_level BETWEEN 0 AND 3),    -- 人の多さ
    water_edge_approach  INTEGER NOT NULL CHECK (water_edge_approach BETWEEN 0 AND 3), -- 水際接近（野川・合流部への接近）
    density_level        INTEGER NOT NULL CHECK (density_level BETWEEN 0 AND 3),  -- 滞留密度
    guardian_supervision INTEGER NOT NULL CHECK (guardian_supervision BETWEEN 0 AND 2), -- 保護者の監視レベル（0複数あり〜2大人不在）
    danger_flags         TEXT,      -- 子ども単独,流れ急変,スリップ（苔・ぬめり）,サンダル流され,吸い込み（合流部）
    site_memo            TEXT,
    event_log            TEXT,
    summary               TEXT,
    ai_summary            TEXT,     -- AI生成サマリー（任意、公的気象データを加味して自動生成）
    report_summary        TEXT,     -- 日次PDF報告書用サマリー（Gemini 2.5 Flash生成・キャッシュ）
    report_generated_at   TEXT,     -- report_summaryの生成日時
    weather_warnings_snapshot   TEXT,     -- 送信時点の気象庁警報・注意報スナップショット（JSON文字列）
    river_level_snapshot_m      REAL,     -- 送信時点の実測水位[m]スナップショット（あれば）
    river_discharge_snapshot_m3s REAL,     -- 送信時点のOpen-Meteo流量シミュレーション参考値[m3/s]スナップショット
    external_snapshot_at         TEXT,     -- 上記スナップショットの取得時刻
    temperature_snapshot_c      REAL,     -- 送信時点の気温[℃]スナップショット
    humidity_snapshot_pct       REAL,     -- 送信時点の湿度[%]スナップショット
    photo_path            TEXT      -- 現場の写真（人工水路・野川水面・空のみ）
);

-- ---------------------------------------------------------
-- セクション4：【兵庫島公園2】（多摩川側）
-- 画像上「*」（必須）が確認できなかった項目は NULL 許容にしています。
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS obs_hyogojima2 (
    observation_id       INTEGER PRIMARY KEY
                          REFERENCES observations(id) ON DELETE CASCADE,

    weather               TEXT NOT NULL CHECK (weather IN (
                              '晴れ','曇り','小雨','雨','強い雨'
                          )),
    water_level           INTEGER CHECK (water_level BETWEEN 0 AND 3),           -- 水位（多摩川本流）※必須マーク未確認
    flow_speed            INTEGER NOT NULL CHECK (flow_speed BETWEEN 0 AND 3),   -- 流速（多摩川本流）
    turbidity             INTEGER NOT NULL CHECK (turbidity BETWEEN 0 AND 3),    -- 濁り
    crowd_level           INTEGER NOT NULL CHECK (crowd_level BETWEEN 0 AND 3),  -- 人の多さ
    water_edge_approach   INTEGER CHECK (water_edge_approach BETWEEN 0 AND 3),   -- 水際接近（多摩川本流への進入）※必須マーク未確認
    density_level         INTEGER CHECK (density_level BETWEEN 0 AND 3),         -- 滞留密度 ※必須マーク未確認
    opposite_bank_impact  INTEGER NOT NULL CHECK (opposite_bank_impact BETWEEN 0 AND 3), -- 対岸（BBQ場側）の状況影響
    danger_flags          TEXT,     -- 本流泳ぎ,対岸からの移動,飛び込み,深みへ転落,飲酒状態の接近
    site_memo             TEXT,
    event_log             TEXT,
    summary                TEXT,
    ai_summary             TEXT,    -- AI生成サマリー（任意、公的気象データを加味して自動生成）
    report_summary        TEXT,     -- 日次PDF報告書用サマリー（Gemini 2.5 Flash生成・キャッシュ）
    report_generated_at   TEXT,     -- report_summaryの生成日時
    weather_warnings_snapshot   TEXT,     -- 送信時点の気象庁警報・注意報スナップショット（JSON文字列）
    river_level_snapshot_m      REAL,     -- 送信時点の実測水位[m]スナップショット（あれば）
    river_discharge_snapshot_m3s REAL,     -- 送信時点のOpen-Meteo流量シミュレーション参考値[m3/s]スナップショット
    external_snapshot_at         TEXT,     -- 上記スナップショットの取得時刻
    temperature_snapshot_c      REAL,     -- 送信時点の気温[℃]スナップショット
    humidity_snapshot_pct       REAL,     -- 送信時点の湿度[%]スナップショット
    photo_path             TEXT     -- 現場の写真（本流・水際・空のみ、最大1枚・10MBまで）
);

CREATE INDEX IF NOT EXISTS idx_observations_area_date
    ON observations(area, observation_date);

-- =========================================================
-- 外部気象・水位データ連携（気象庁／国交省）
-- =========================================================

-- 気象庁・水位の最新取得結果を1行だけ保持するキャッシュテーブル
-- （フォームを開いた瞬間 or 定期ジョブで更新される想定）
CREATE TABLE IF NOT EXISTS external_status_cache (
    id                 INTEGER PRIMARY KEY CHECK (id = 1), -- 常に1行のみ
    fetched_at         TEXT NOT NULL,             -- 取得日時
    jma_area_code      TEXT,                      -- 気象庁 地域コード（世田谷区=1311200）
    jma_warnings_json   TEXT,                      -- 発令中の警報・注意報一覧（JSON文字列）
    jma_report_time     TEXT,                      -- 気象庁発表時刻
    river_level_m       REAL,                      -- 多摩川（二子橋付近）実測水位[m]（契約API or 手動入力）
    river_level_source  TEXT,                      -- 'contracted_api'（正規契約API）or 'manual'（スタッフ手動入力）
    river_level_fetched_at TEXT,                   -- 実測水位データの取得/入力時刻
    river_discharge_m3s   REAL,                     -- Open-Meteo Flood API：河川流量シミュレーション値[m3/s]（参考値）
    river_discharge_date  TEXT,                     -- 流量シミュレーション値の対象日
    temperature_c         REAL,                     -- 気象実況：気温[℃]（Open-Meteo）
    humidity_pct          REAL,                     -- 気象実況：湿度[%]（Open-Meteo）
    weather_code          INTEGER,                  -- 気象実況：天気コード（Open-Meteo WMOコード）
    alert_level          TEXT CHECK (alert_level IN ('normal','caution','danger')) DEFAULT 'normal'
);

-- 直近24時間トレンド用の履歴（get_external_statusが実際に取得するたびに1行追加。48時間より古い行は自動削除）
CREATE TABLE IF NOT EXISTS external_status_history (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at         TEXT NOT NULL,
    river_level_m      REAL,
    river_discharge_m3s REAL,
    temperature_c      REAL,
    humidity_pct       REAL
);
CREATE INDEX IF NOT EXISTS idx_external_status_history_fetched_at
    ON external_status_history(fetched_at);

-- 水位オープンデータAPIが未契約の場合の、スタッフによる手動入力バックアップ
-- （公式サイト「川の防災情報」を目視確認したうえで入力する運用を想定）
CREATE TABLE IF NOT EXISTS river_level_manual_entry (
    id            INTEGER PRIMARY KEY CHECK (id = 1), -- 常に1行のみ
    level_m       REAL NOT NULL,
    observed_at   TEXT NOT NULL,      -- 現地で確認した時刻
    entered_by    TEXT,               -- 入力した観測員ID
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 観測データ全体に対して、閾値超過時に画面アラートを出した記録（監査用ログ、任意）
CREATE TABLE IF NOT EXISTS alert_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reason        TEXT,               -- 例：'大雨警報発令', '氾濫危険水位超過'
    river_level_m REAL,
    warnings_json TEXT
);
