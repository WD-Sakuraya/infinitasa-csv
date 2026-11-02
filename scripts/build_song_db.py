"""bemaniwikiの「beatmania IIDX INFINITAS/全曲リスト」から楽曲DBを生成する。

出力: data/song_db.csv (タイトル, バージョン, ジャンル, アーティスト, 各難易度レベルなど)
"""
import argparse
import csv
import re
import sys

import requests
from bs4 import BeautifulSoup

SONG_LIST_URL = (
    "https://bemaniwiki.com/?beatmania+IIDX+INFINITAS/"
    "%E5%85%A8%E6%9B%B2%E3%83%AA%E3%82%B9%E3%83%88"
)

OUTPUT_COLUMNS = [
    "バージョン",
    "区分",
    "タイトル",
    "ジャンル",
    "アーティスト",
    "SP_BEGINNER",
    "SP_NORMAL",
    "SP_HYPER",
    "SP_ANOTHER",
    "SP_LEGGENDARIA",
    "DP_NORMAL",
    "DP_HYPER",
    "DP_ANOTHER",
    "DP_LEGGENDARIA",
    "BPM",
]

# bemaniwikiの見出しテキストは番号とタイトルの間にスペースが無いことがあり、
# そのまま除去すると公式表記と単語がくっついてしまうケースの補正。
VERSION_NAME_OVERRIDES = {
    "CANNONBALLERS": "CANNON BALLERS",
    "PinkyCrush": "Pinky Crush",
}

STYLE_SUFFIX_RE = re.compile(r"^\d+(st|nd|rd|th) style$")
LEADING_NUMBER_RE = re.compile(r"^\d+\s*(.*)$")


def normalize_version(raw_heading: str) -> str:
    text = raw_heading.replace("▲", "").replace("▼", "").replace("△", "").strip()
    text = text.removeprefix("beatmania IIDX").strip()

    if text == "":
        return "1st style"
    if STYLE_SUFFIX_RE.match(text):
        return text

    m = LEADING_NUMBER_RE.match(text)
    if m:
        remainder = m.group(1).strip()
        if remainder:
            return VERSION_NAME_OVERRIDES.get(remainder, remainder)

    return VERSION_NAME_OVERRIDES.get(text, text)


def fetch_html(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def find_song_table(soup: BeautifulSoup):
    body = soup.find("div", id="body") or soup
    for table in body.find_all("table"):
        first_row = table.find("tr")
        if not first_row:
            continue
        header_text = "".join(
            c.get_text(strip=True) for c in first_row.find_all(["th", "td"])
        )
        if "区分" in header_text and "GENRE" in header_text and "TITLE" in header_text:
            return table
    raise RuntimeError("曲リストのテーブルが見つかりませんでした(ページ構造が変わった可能性があります)")


def parse_songs(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = find_song_table(soup)
    rows = table.find_all("tr")

    songs = []
    current_version = None

    for row in rows:
        cells = row.find_all(["th", "td"])
        if not cells:
            continue

        if len(cells) == 1 and cells[0].get("colspan"):
            current_version = normalize_version(cells[0].get_text(strip=True))
            continue

        if len(cells) < 14:
            # サブヘッダー行(B N H A L ...)やレイアウト崩れはスキップ
            continue

        values = [c.get_text(strip=True) for c in cells]
        (
            kubun,
            sp_b, sp_n, sp_h, sp_a, sp_l,
            dp_n, dp_h, dp_a, dp_l,
            bpm, genre, title, artist,
        ) = values[:14]

        if not title:
            continue

        songs.append(
            {
                "バージョン": current_version or "",
                "区分": kubun,
                "タイトル": title,
                "ジャンル": genre,
                "アーティスト": artist,
                "SP_BEGINNER": sp_b,
                "SP_NORMAL": sp_n,
                "SP_HYPER": sp_h,
                "SP_ANOTHER": sp_a,
                "SP_LEGGENDARIA": sp_l,
                "DP_NORMAL": dp_n,
                "DP_HYPER": dp_h,
                "DP_ANOTHER": dp_a,
                "DP_LEGGENDARIA": dp_l,
                "BPM": bpm,
            }
        )

    return songs


def write_csv(songs, out_path: str):
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(songs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        help="ローカルに保存済みのHTMLファイルを使う場合のパス(省略時はWebから取得)",
    )
    parser.add_argument(
        "--output",
        default="data/song_db.csv",
        help="出力CSVのパス(既定: data/song_db.csv)",
    )
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8", errors="replace") as f:
            html = f.read()
    else:
        html = fetch_html(SONG_LIST_URL)

    songs = parse_songs(html)
    if not songs:
        print("警告: 曲データを1件も取得できませんでした", file=sys.stderr)
        sys.exit(1)

    write_csv(songs, args.output)
    print(f"{len(songs)} 曲を {args.output} に書き出しました")


if __name__ == "__main__":
    main()
