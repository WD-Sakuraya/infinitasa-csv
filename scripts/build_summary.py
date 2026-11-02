"""data/history.csv(プレー単位の履歴)から、曲単位の自己ベスト集計CSVを生成する。

出力フォーマットは `2253-2531_sp_score.csv` と互換(1曲1行、各難易度の自己ベストのみ)。
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

DIFFICULTIES = ["BEGINNER", "NORMAL", "HYPER", "ANOTHER", "LEGGENDARIA"]

SUMMARY_HEADER = ["バージョン", "タイトル", "ジャンル", "アーティスト", "プレー回数"]
for d in DIFFICULTIES:
    SUMMARY_HEADER += [
        f"{d} 難易度",
        f"{d} スコア",
        f"{d} PGreat",
        f"{d} Great",
        f"{d} ミスカウント",
        f"{d} クリアタイプ",
        f"{d} DJ LEVEL",
    ]
SUMMARY_HEADER.append("最終プレー日時")

EMPTY_DIFFICULTY = {
    "難易度": "0",
    "スコア": "0",
    "PGreat": "0",
    "Great": "0",
    "ミスカウント": "---",
    "クリアタイプ": "NO PLAY",
    "DJ LEVEL": "---",
}


def load_history(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_song_order(song_db_path: str) -> dict[str, int]:
    """song_db.csvの出現順(=バージョンの時系列順)をタイトルの並び替えに使う。"""
    order = {}
    if not os.path.exists(song_db_path):
        return order
    with open(song_db_path, encoding="utf-8-sig", newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            order.setdefault(row["タイトル"], i)
    return order


def build_summary(history_rows: list[dict]) -> list[dict]:
    by_title: dict[str, list[dict]] = defaultdict(list)
    for row in history_rows:
        by_title[row["タイトル"]].append(row)

    summary_rows = []
    for title, rows in by_title.items():
        first = rows[0]
        version = first["バージョン"]
        genre = first["ジャンル"]
        artist = first["アーティスト"]
        play_count = len(rows)
        last_played = max(r["取込日時"] for r in rows)

        by_difficulty: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_difficulty[r["難易度"]].append(r)

        out_row = {
            "バージョン": version,
            "タイトル": title,
            "ジャンル": genre,
            "アーティスト": artist,
            "プレー回数": play_count,
            "最終プレー日時": last_played,
        }

        for d in DIFFICULTIES:
            d_rows = by_difficulty.get(d, [])
            if not d_rows:
                best = EMPTY_DIFFICULTY
            else:
                best_row = max(d_rows, key=lambda r: int(r["スコア"]))
                best = {
                    "難易度": best_row["難易度数値"],
                    "スコア": best_row["スコア"],
                    "PGreat": best_row["PGreat"],
                    "Great": best_row["Great"],
                    "ミスカウント": best_row["ミスカウント"],
                    "クリアタイプ": best_row["クリアタイプ"],
                    "DJ LEVEL": best_row["DJ LEVEL"],
                }
            for key, value in best.items():
                out_row[f"{d} {key}"] = value

        summary_rows.append(out_row)

    return summary_rows


def write_summary(rows: list[dict], out_path: str, song_order: dict[str, int]) -> None:
    rows.sort(key=lambda r: (song_order.get(r["タイトル"], len(song_order)), r["タイトル"]))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history", default="data/history.csv", help="履歴CSVのパス(既定: data/history.csv)"
    )
    parser.add_argument(
        "--song-db", default="data/song_db.csv", help="並び順の参照に使う楽曲DB(既定: data/song_db.csv)"
    )
    parser.add_argument(
        "--output", default="data/summary.csv", help="出力先(既定: data/summary.csv)"
    )
    args = parser.parse_args()

    if not os.path.exists(args.history):
        print(f"エラー: 履歴CSVが見つかりません: {args.history}", file=sys.stderr)
        sys.exit(1)

    history_rows = load_history(args.history)
    summary_rows = build_summary(history_rows)
    song_order = build_song_order(args.song_db)
    write_summary(summary_rows, args.output, song_order)

    print(f"{len(summary_rows)} 曲分の集計を {args.output} に書き出しました")


if __name__ == "__main__":
    main()
