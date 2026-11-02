"""beatmania IIDX INFINITASのリザルト画面の写真を解析し、履歴CSVに1行追記する。

使い方:
    python scripts/extract_result.py image.jpg
    python scripts/extract_result.py image1.jpg image2.jpg ...

必要な環境変数: ANTHROPIC_API_KEY (または `ant auth login` 済みであること)
"""
import argparse
import csv
import datetime
import os
import sys

import anthropic

from iidx_extract import HISTORY_COLUMNS, build_history_row, extract_from_image
from song_match import SongRow, load_song_db, resolve_title


def prompt_user_for_title(ocr_title: str, candidates) -> str | None:
    print(f"\n  曲名の自動判定ができませんでした(OCR結果: 「{ocr_title}」)")
    print("  候補:")
    for i, c in enumerate(candidates, start=1):
        print(f"    {i}. {c.song.title} / {c.song.artist} ({c.song.version})  類似度={c.score:.2f}")
    print("    0. 候補になし(タイトルを手入力する)")
    print("    s. この写真をスキップ")

    choice = input("  選択してください: ").strip()
    if choice.lower() == "s":
        return None
    if choice == "0":
        manual = input("  正しいタイトルを入力してください: ").strip()
        return manual
    try:
        idx = int(choice)
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1].song.title
    except ValueError:
        pass

    print("  無効な入力です。この写真をスキップします。")
    return None


def append_history(row: dict, history_path: str) -> None:
    file_exists = os.path.exists(history_path)
    os.makedirs(os.path.dirname(history_path) or ".", exist_ok=True)
    with open(history_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def process_image(
    client: anthropic.Anthropic, image_path: str, songs, history_path: str, captured_at: str
) -> bool:
    print(f"\n[解析中] {image_path}")
    data = extract_from_image(client, image_path)

    if data["unclear_fields"]:
        print(f"  注意: 読み取りに自信が無いフィールド: {', '.join(data['unclear_fields'])}")

    song, candidates = resolve_title(data["title"], songs)
    if song is None:
        title = prompt_user_for_title(data["title"], candidates)
        if title is None:
            print("  スキップしました。")
            return False
        matches = [s for s in songs if s.title == title]
        if not matches:
            print(f"  警告: 「{title}」はsong_db.csvに見つかりません。バージョン/ジャンルは空で記録します。")
            song = SongRow(version="", title=title, genre="", artist=data["artist"])
        else:
            song = matches[0]
    else:
        print(f"  曲を特定しました: {song.title} / {song.artist} ({song.version})")

    row = build_history_row(data, song, image_path, captured_at)
    append_history(row, history_path)
    print(f"  {history_path} に追記しました。")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", help="リザルト画面の画像ファイル")
    parser.add_argument(
        "--song-db", default="data/song_db.csv", help="楽曲DBのパス(既定: data/song_db.csv)"
    )
    parser.add_argument(
        "--history", default="data/history.csv", help="履歴CSVの出力先(既定: data/history.csv)"
    )
    parser.add_argument(
        "--date",
        default=None,
        help="取込日時を指定(既定: 実行時の現在日時)。例: 2026-11-02",
    )
    args = parser.parse_args()

    if not os.path.exists(args.song_db):
        print(f"エラー: 楽曲DBが見つかりません: {args.song_db}", file=sys.stderr)
        print("先に `python scripts/build_song_db.py` を実行してください。", file=sys.stderr)
        sys.exit(1)

    songs = load_song_db(args.song_db)
    captured_at = args.date or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    client = anthropic.Anthropic()

    ok_count = 0
    for image_path in args.images:
        try:
            if process_image(client, image_path, songs, args.history, captured_at):
                ok_count += 1
        except anthropic.APIStatusError as e:
            print(f"  APIエラー: {e.message}", file=sys.stderr)
        except Exception as e:
            print(f"  エラー: {e}", file=sys.stderr)

    print(f"\n完了: {ok_count}/{len(args.images)} 件を記録しました。")


if __name__ == "__main__":
    main()
