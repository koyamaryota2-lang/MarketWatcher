#!/usr/bin/env python3
"""
daily_market_watcher.py

毎日の主要マーケット指標と日本株業種の強弱を取得して表示・記録するスクリプト。
- 米10年金利
- ドル円 (USD/JPY)
- 米国株価指数 (S&P500 / NASDAQ / NYダウ)
- WTI原油先物
- 銅先物
- TOPIX-17 業種ETFの日次騰落率

出力はテーブル画像（色グラデーション付き、日本の相場慣習に合わせて上昇=赤、下落=青）
としてDiscordに送信されます。コンソールにも簡易カラー表を出力します。

毎朝8時の確認を想定し、各市場の直近取得値、24時間比または前日比、5営業日前比、
1か月前比、3か月前比を表示します。

必要ライブラリ:
    pip install yfinance requests matplotlib

Discord通知を使う場合:
    1. Discordのチャンネル設定 → 連携サービス → ウェブフックを作成し、URLをコピー
    2. 環境変数 DISCORD_WEBHOOK_URL にセット（GitHub Actionsの場合はSecretsに登録）

実行方法:
    python daily_market_watcher.py
"""

import csv
import io
import json
import os
import sys
import unicodedata
from datetime import datetime, timedelta

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance がインストールされていません。 'pip install yfinance' を実行してください。")

try:
    import requests
except ImportError:
    requests = None  # Discord通知を使わないなら無くてもOK

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
except ImportError:
    plt = None  # 画像テーブルを使わないなら無くてもOK

# 環境変数 DISCORD_WEBHOOK_URL で渡す(コード内に直接書かない)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


MACRO_INSTRUMENTS = {
    "米10年金利": {"ticker": "^TNX", "unit": "%", "decimals": 3, "change_mode": "absolute"},
    "ドル円": {
        "ticker": "JPY=X", "unit": "", "decimals": 2, "change_mode": "absolute", "use_24h": True,
    },
    "WTI原油": {
        "ticker": "CL=F", "unit": "", "decimals": 2, "change_mode": "percent", "use_24h": True,
    },
    "銅": {
        "ticker": "HG=F", "unit": "", "decimals": 2, "change_mode": "percent", "use_24h": True,
    },
    "ゴールド": {
        "ticker": "GC=F", "unit": "", "decimals": 2, "change_mode": "percent", "use_24h": True,
    },
    "日本国債10年(ETF代用・価格は利回りと逆方向)": {
        "ticker": "2561.T", "unit": "", "decimals": 2, "change_mode": "percent",
    },
}

JAPAN_INDEX_INSTRUMENTS = {
    "日経平均": {"ticker": "^N225", "unit": "", "decimals": 2, "change_mode": "percent"},
    "TOPIX(ETF代用)": {"ticker": "1306.T", "unit": "", "decimals": 2, "change_mode": "percent"},
}

US_INDEX_INSTRUMENTS = {
    "S&P500": {"ticker": "^GSPC", "unit": "", "decimals": 2, "change_mode": "percent"},
    "NASDAQ": {"ticker": "^IXIC", "unit": "", "decimals": 2, "change_mode": "percent"},
    "NYダウ": {"ticker": "^DJI", "unit": "", "decimals": 2, "change_mode": "percent"},
    "VIX(恐怖指数)": {"ticker": "^VIX", "unit": "", "decimals": 2, "change_mode": "percent"},
}

MARKET_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_log.csv")
SECTOR_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_log_jp.csv")
TABLE_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "table_images")

SECTOR_ETFS = {
    "食品": "1617.T",
    "エネルギー資源": "1618.T",
    "建設・資材": "1619.T",
    "素材・化学": "1620.T",
    "医薬品": "1621.T",
    "自動車・輸送機": "1622.T",
    "鉄鋼・非鉄": "1623.T",
    "機械": "1624.T",
    "電機・精密": "1625.T",
    "情報通信・サービス他": "1626.T",
    "電力・ガス": "1627.T",
    "運輸・物流": "1628.T",
    "商社・卸売": "1629.T",
    "小売": "1630.T",
    "銀行": "1631.T",
    "金融(除く銀行)": "1632.T",
    "不動産": "1633.T",
}

# 色グラデーションの基準となる変動幅(この%を超えたら最大濃度になる)
COLOR_VMAX_PERCENT = 3.0

# 日本語フォント候補(存在するものが自動選択される)
JAPANESE_FONT_CANDIDATES = [
    "Noto Sans CJK JP", "IPAexGothic", "Yu Gothic", "Meiryo",
    "Hiragino Sans", "TakaoGothic", "sans-serif",
]


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

def fetch_latest(ticker: str, use_24h: bool = False):
    """直近値、比較値、5営業日前、約1か月前、約3か月前の終値を取得"""
    data = yf.Ticker(ticker).history(period="180d", interval="1d", auto_adjust=False)
    closes = data["Close"].dropna() if not data.empty else None
    if closes is None or closes.empty:
        return None, None, None, None, None
    latest_close = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2]) if len(closes) > 1 else None
    five_day_close = float(closes.iloc[-6]) if len(closes) > 5 else None
    month_close = float(closes.iloc[-22]) if len(closes) > 21 else None
    quarter_close = float(closes.iloc[-66]) if len(closes) > 65 else None

    if use_24h:
        intraday = yf.Ticker(ticker).history(
            period="5d", interval="1h", auto_adjust=False
        )
        intraday_closes = intraday["Close"].dropna() if not intraday.empty else None
        if intraday_closes is not None and len(intraday_closes) > 1:
            latest_time = intraday_closes.index[-1]
            target_time = latest_time - timedelta(hours=24)
            reference_time = min(
                intraday_closes.index,
                key=lambda timestamp: abs((timestamp - target_time).total_seconds()),
            )
            latest_close = float(intraday_closes.iloc[-1])
            prev_close = float(intraday_closes.loc[reference_time])

    return latest_close, prev_close, five_day_close, month_close, quarter_close


def compute_pct(latest, reference):
    """色グラデーション判定用に常にパーセント換算した変化率を返す"""
    if latest is None or reference is None or reference == 0:
        return None
    return (latest - reference) / reference * 100


def format_directional_change(change: float, decimals: int = 2):
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.{decimals}f}%"


def format_change_display(latest, reference, decimals: int = 2, mode: str = "percent"):
    """テーブルセルに表示する文字列を作る"""
    if latest is None or reference is None or reference == 0:
        return "データ不足"
    change = latest - reference
    if mode == "absolute":
        sign = "+" if change >= 0 else ""
        return f"{sign}{change:.{decimals}f}"
    pct = (change / reference) * 100
    return format_directional_change(pct, decimals=2)


def fetch_sector_change(ticker: str):
    latest, prev, five_day_close, month_close, quarter_close = fetch_latest(ticker)
    if latest is None:
        return None, None, None, None, None
    return latest, prev, five_day_close, month_close, quarter_close


def append_csv_row(file_path: str, row: dict):
    write_header = not os.path.exists(file_path)
    with open(file_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def display_width(text: str):
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in ("F", "W", "A") else 1
    return width


def pad_label(text: str, target_width: int = 20):
    padding = max(target_width - display_width(text), 0)
    return text + (" " * padding)


def format_value(value: float, unit: str, decimals: int):
    if unit == "%":
        return f"{value:.{decimals}f}{unit}"
    return f"{value:,.{decimals}f}"


# ---------------------------------------------------------------------------
# 行データの組み立て (画像テーブル・コンソール共通)
# ---------------------------------------------------------------------------

def build_market_rows(instruments: dict):
    """
    各行を辞書で返す:
    {
        "name": str, "close": str,
        "cells": [(表示文字列, 色判定用pct), ...]  # 1D, 5D, 1M, 3M の順
    }
    """
    rows = []
    raw_results = {}
    for name, metadata in instruments.items():
        ticker = metadata["ticker"]
        try:
            latest, prev, five_day_close, month_close, quarter_close = fetch_latest(
                ticker, use_24h=metadata.get("use_24h", False)
            )
            if latest is None:
                rows.append({"name": name, "close": "データ取得失敗", "cells": [("-", None)] * 4})
                continue

            close_str = format_value(latest, metadata["unit"], metadata["decimals"])
            mode = metadata["change_mode"]
            decimals = metadata["decimals"]
            cells = [
                (format_change_display(latest, prev, decimals, mode), compute_pct(latest, prev)),
                (format_change_display(latest, five_day_close, decimals, mode), compute_pct(latest, five_day_close)),
                (format_change_display(latest, month_close, decimals, mode), compute_pct(latest, month_close)),
                (format_change_display(latest, quarter_close, decimals, mode), compute_pct(latest, quarter_close)),
            ]
            rows.append({"name": name, "close": close_str, "cells": cells})
            raw_results[name] = round(latest, 4)
        except Exception as e:
            rows.append({"name": name, "close": f"エラー", "cells": [("-", None)] * 4})
            print(f"[警告] {name} の取得でエラー: {e}")

    return rows, raw_results


def build_sector_rows():
    rows = []
    raw_results = {}
    for name, ticker in SECTOR_ETFS.items():
        try:
            latest, prev, five_day_close, month_close, quarter_close = fetch_sector_change(ticker)
            if latest is None:
                rows.append({"name": name, "close": "データ取得失敗", "cells": [("-", None)] * 4}, )
                continue
            daily_pct = compute_pct(latest, prev)
            close_str = f"{latest:,.1f}"
            cells = [
                (format_directional_change(daily_pct) if daily_pct is not None else "データ不足", daily_pct),
                (
                    format_directional_change(compute_pct(latest, five_day_close))
                    if five_day_close else "データ不足",
                    compute_pct(latest, five_day_close),
                ),
                (
                    format_directional_change(compute_pct(latest, month_close))
                    if month_close else "データ不足",
                    compute_pct(latest, month_close),
                ),
                (
                    format_directional_change(compute_pct(latest, quarter_close))
                    if quarter_close else "データ不足",
                    compute_pct(latest, quarter_close),
                ),
            ]
            rows.append({"name": name, "close": close_str, "cells": cells, "_sort": daily_pct})
            if daily_pct is not None:
                raw_results[name] = round(daily_pct, 2)
        except Exception as e:
            rows.append({"name": name, "close": "エラー", "cells": [("-", None)] * 4, "_sort": float("-inf")})
            print(f"[警告] {name} の取得でエラー: {e}")

    # 前日比が大きい順にソート(業種の強弱が一目でわかるように)
    rows.sort(key=lambda r: r.get("_sort", float("-inf")) if r.get("_sort") is not None else float("-inf"), reverse=True)
    return rows, raw_results


# ---------------------------------------------------------------------------
# 色グラデーション (日本の相場慣習: 上昇=赤 / 下落=青)
# ---------------------------------------------------------------------------

def pct_to_hex_color(pct, vmax=COLOR_VMAX_PERCENT):
    """変化率(%)を背景色(HEX)に変換。米国式: 上昇=緑系、下落=赤系のグラデーション。"""
    if pct is None:
        return "#EEEEEE"
    intensity = min(abs(pct) / vmax, 1.0)
    if pct >= 0:
        r = int(255 - intensity * 175)
        g = 255
        b = int(255 - intensity * 175)
    else:
        r = 255
        g = int(255 - intensity * 175)
        b = int(255 - intensity * 175)
    return f"#{r:02x}{g:02x}{b:02x}"


def pct_to_discord_ansi(pct, vmax=COLOR_VMAX_PERCENT):
    """Discordの```ansi```コードブロック用エスケープコード。上昇=緑、下落=赤。"""
    if pct is None:
        return "", ""
    intensity = min(abs(pct) / vmax, 1.0)
    reset = "\u001b[0m"
    if pct >= 0:
        code = "\u001b[1;32m" if intensity > 0.5 else "\u001b[0;32m"
    else:
        code = "\u001b[1;31m" if intensity > 0.5 else "\u001b[0;31m"
    return code, reset


def build_discord_ansi_table(rows: list, name_width: int = 24, close_width: int = 14, cell_width: int = 10):
    """rowsから Discord の ```ansi``` コードブロック文字列を作る"""
    header = f"{pad_label('名称', name_width)}{pad_label('終値', close_width)}"
    header += "".join(pad_label(h, cell_width) for h in ["1D", "5D", "1M", "3M"])
    lines = [header, "-" * display_width(header)]
    for row in rows:
        line = pad_label(row["name"], name_width) + pad_label(row["close"], close_width)
        for disp, pct in row["cells"]:
            code, reset = pct_to_discord_ansi(pct)
            pad_n = max(cell_width - display_width(disp), 0)
            colored = f"{code}{disp}{reset}" if code else disp
            line += (" " * pad_n) + colored
        lines.append(line)
    return "```ansi\n" + "\n".join(lines) + "\n```"


def pct_to_ansi(pct, vmax=COLOR_VMAX_PERCENT):
    """コンソール表示用のANSIエスケープコード(前景色)を返す。米国式: 上昇=緑、下落=赤。"""
    reset = "\033[0m"
    if pct is None:
        return "", reset
    intensity = min(abs(pct) / vmax, 1.0)
    if pct >= 0:
        code = "\033[1;92m" if intensity > 0.5 else "\033[32m"
    else:
        code = "\033[1;91m" if intensity > 0.5 else "\033[31m"
    return code, reset


# ---------------------------------------------------------------------------
# コンソール表示 (簡易カラー表)
# ---------------------------------------------------------------------------

def print_console_table(title: str, rows: list):
    print(f"\n--- {title} ---")
    header = f"{pad_label('名称', 22)}{pad_label('終値', 12)}{'1D':>10}{'5D':>10}{'1M':>10}{'3M':>10}"
    print(header)
    print("-" * display_width(header))
    for row in rows:
        line = f"{pad_label(row['name'], 22)}{pad_label(row['close'], 12)}"
        for display_str, pct in row["cells"]:
            color, reset = pct_to_ansi(pct)
            colored = f"{color}{display_str}{reset}" if color else display_str
            # 色コードは表示幅に影響しないので、素の文字列で幅を計算してパディング
            pad = max(10 - display_width(display_str), 0)
            line += (" " * pad) + colored
        print(line)


# ---------------------------------------------------------------------------
# 画像テーブル生成 (Discord添付用)
# ---------------------------------------------------------------------------

def setup_japanese_font():
    if plt is None:
        return
    available = {f.name for f in fm.fontManager.ttflist}
    for candidate in JAPANESE_FONT_CANDIDATES:
        if candidate in available or candidate == "sans-serif":
            plt.rcParams["font.family"] = candidate
            return
    plt.rcParams["font.family"] = "sans-serif"


def render_table_image(rows: list, title: str, filepath: str, note: str = None):
    """rowsから色グラデーション付きテーブル画像(PNG)を生成する"""
    if plt is None:
        print("matplotlibが無いため画像テーブルはスキップしました。")
        return None

    setup_japanese_font()

    headers = ["名称", "終値", "1D", "5D", "1M", "3M"]
    cell_text = []
    cell_colors = []
    for row in rows:
        display_cells = [d for d, _ in row["cells"]]
        pct_cells = [p for _, p in row["cells"]]
        cell_text.append([row["name"], row["close"]] + display_cells)
        row_colors = ["#FFFFFF", "#FFFFFF"] + [pct_to_hex_color(p) for p in pct_cells]
        cell_colors.append(row_colors)

    n_rows = len(rows)
    fig_height = 0.9 + 0.38 * n_rows + (0.3 if note else 0)
    fig, ax = plt.subplots(figsize=(8.5, fig_height))
    ax.axis("off")
    ax.set_title(title, fontsize=15, fontweight="bold", pad=14)
    if note:
        ax.text(0.5, 1.02, note, transform=ax.transAxes, ha="center", fontsize=8, color="#666666")

    table = ax.table(
        cellText=cell_text,
        colLabels=headers,
        cellColours=cell_colors,
        colColours=["#DDDDDD"] * len(headers),
        loc="center",
        cellLoc="center",
        colWidths=[0.28, 0.16, 0.14, 0.14, 0.14, 0.14],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.6)

    fig.tight_layout()
    fig.savefig(filepath, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return filepath


# ---------------------------------------------------------------------------
# Discord通知 (テキスト表、画像なし)
# ---------------------------------------------------------------------------

def send_discord_text_tables(message: str, sections: list):
    """
    sections: [(title, rows, note), ...]
    画像を使わず、```ansi```コードブロックのテキスト表としてDiscordに送信する。
    embedのdescriptionに表を入れる(1embedあたり4096文字まで)。
    """
    if not requests:
        print("requestsがインストールされていないため、Discord通知はスキップしました。")
        return
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URLが未設定のため、Discord通知はスキップしました。")
        return

    embeds = []
    for title, rows, note in sections:
        if not rows:
            continue
        table_text = build_discord_ansi_table(rows)
        description = f"{note}\n{table_text}" if note else table_text
        if len(description) > 4096:
            description = description[:4000] + "\n...(省略)\n```"
        embeds.append({
            "title": title,
            "color": 3447003,
            "description": description,
        })

    payload = {"content": message, "embeds": embeds}

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=20)
        if resp.status_code not in (200, 204):
            print(f"Discord通知に失敗しました: status={resp.status_code}, body={resp.text}")
    except Exception as e:
        print(f"Discord通知でエラー: {e}")


# ---------------------------------------------------------------------------
# Discord通知 (画像添付・任意で利用可能)
# ---------------------------------------------------------------------------

def send_discord_with_images(message: str, image_paths_with_titles: list):
    """
    image_paths_with_titles: [(filepath, title), ...]
    各画像を1つのメッセージに複数添付し、embedで表示する
    """
    if not requests:
        print("requestsがインストールされていないため、Discord通知はスキップしました。")
        return
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URLが未設定のため、Discord通知はスキップしました。")
        return

    files = {}
    embeds = []
    for i, (filepath, embed_title) in enumerate(image_paths_with_titles):
        if not filepath or not os.path.exists(filepath):
            continue
        filename = f"table_{i}.png"
        files[f"files[{i}]"] = (filename, open(filepath, "rb"), "image/png")
        embeds.append({
            "title": embed_title,
            "color": 3447003,
            "image": {"url": f"attachment://{filename}"},
        })

    payload = {"content": message, "embeds": embeds}

    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            data={"payload_json": json.dumps(payload)},
            files=files,
            timeout=20,
        )
        if resp.status_code not in (200, 204):
            print(f"Discord通知に失敗しました: status={resp.status_code}, body={resp.text}")
    except Exception as e:
        print(f"Discord通知でエラー: {e}")
    finally:
        for _, (_, fh, _) in files.items():
            fh.close()


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main():
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n=== デイリーマーケット概況 {today} ===")
    print("※値は各市場の直近取得済み終値です。24時間市場(ドル円/原油/銅)は直近24時間比、")
    print("  それ以外は前営業日比・5営業日比・1か月比・3か月比を表示します。")

    os.makedirs(TABLE_IMAGE_DIR, exist_ok=True)

    macro_rows, macro_results = build_market_rows(MACRO_INSTRUMENTS)
    japan_index_rows, japan_index_results = build_market_rows(JAPAN_INDEX_INSTRUMENTS)
    us_index_rows, us_index_results = build_market_rows(US_INDEX_INSTRUMENTS)
    sector_rows, sector_results = build_sector_rows()

    print_console_table("マクロ指標", macro_rows)
    print_console_table("日本株指数", japan_index_rows)
    print_console_table("米国株指数", us_index_rows)
    print_console_table("TOPIX-17 業種騰落率", sector_rows)

    # CSV保存(従来通り)
    combined_market_results = {"日時": today}
    combined_market_results.update(macro_results)
    combined_market_results.update(japan_index_results)
    combined_market_results.update(us_index_results)
    sector_results_with_date = {"日時": today}
    sector_results_with_date.update(sector_results)
    append_csv_row(MARKET_LOG_FILE, combined_market_results)
    append_csv_row(SECTOR_LOG_FILE, sector_results_with_date)
    print(f"\n履歴を {MARKET_LOG_FILE} に保存しました。")
    print(f"履歴を {SECTOR_LOG_FILE} に保存しました。")

    # 画像テーブル生成してDiscordに送信
    macro_image = render_table_image(
        macro_rows, "マクロ指標",
        os.path.join(TABLE_IMAGE_DIR, "macro.png"),
        note="24時間市場(ドル円/原油/銅/ゴールド)は直近24時間比、それ以外は前営業日比。国債はETF価格(利回りと逆方向)",
    )
    japan_index_image = render_table_image(
        japan_index_rows, "日本株指数",
        os.path.join(TABLE_IMAGE_DIR, "japan_index.png"),
        note="TOPIXは連動ETF(1306.T)の価格で代用",
    )
    us_index_image = render_table_image(
        us_index_rows, "米国株指数",
        os.path.join(TABLE_IMAGE_DIR, "us_index.png"),
    )
    sector_image = render_table_image(
        sector_rows, "TOPIX-17 業種騰落率(前日比が大きい順)",
        os.path.join(TABLE_IMAGE_DIR, "sector.png"),
    )

    send_discord_with_images(
        f"**デイリーマーケット概況 {today}**",
        [
            (macro_image, "マクロ指標"),
            (japan_index_image, "日本株指数"),
            (us_index_image, "米国株指数"),
            (sector_image, "TOPIX-17 業種騰落率"),
        ],
    )


if __name__ == "__main__":
    main()