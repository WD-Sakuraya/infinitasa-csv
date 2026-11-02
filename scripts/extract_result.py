"""beatmania IIDX INFINITASのリザルト画面の写真を解析し、履歴CSVに1行追記する。

使い方:
    python scripts/extract_result.py image.jpg
    python scripts/extract_result.py image1.jpg image2.jpg ...

必要な環境変数: ANTHROPIC_API_KEY (または `ant auth login` 済みであること)
"""
import argparse
import base64
import csv
import datetime
import json
import mimetypes
import os
import sys

import anthropic

from song_match import load_song_db, resolve_title

MODEL = "claude-opus-5-5"

HISTORY_COLUMNS = [
    "取込日時",
    "タイトル",
    "バージョン",
    "ジャンル",
    "アーティスト",
    "モード",
    "難易度",
    "難易度数値",
    "ノーツ数",
    "スコア",
    "スコア自己ベスト差分",
    "PGreat",
    "Great",
    "Good",
    "Bad",
    "Poor",
    "ミスカウント",
    "ミスカウント自己ベスト差分",
    "クリアタイプ",
    "DJ LEVEL",
    "DJ LEVEL基準点差分",
    "自己ベスト更新(スコア)",
    "自己ベスト更新(ミスカウント)",
    "元画像",
]

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "曲名"},
        "artist": {"type": "string", "description": "アーティスト名"},
        "mode": {"type": "string", "enum": ["SP", "DP"]},
        "difficulty": {
            "type": "string",
            "enum": ["BEGINNER", "NORMAL", "HYPER", "ANOTHER", "LEGGENDARIA"],
        },
        "level": {"type": "integer", "description": "難易度の数値(譜面レベル)"},
        "notes": {
            "type": ["integer", "null"],
            "description": "ノーツ数。表示が無ければnull",
        },
        "clear_type": {
            "type": "string",
            "description": "今回のプレーのクリアタイプ(例: FAILED, ASSIST CLEAR, EASY CLEAR, CLEAR, HARD CLEAR, EX HARD CLEAR, FULLCOMBO CLEAR)",
        },
        "dj_level_rank": {
            "type": "string",
            "description": "今回のプレーのDJ LEVELランク文字(例: B, A, AA, AAA, F)",
        },
        "dj_level_diff": {
            "type": ["integer", "null"],
            "description": "DJ LEVELランクの基準点からの差分点数(符号付き、例: B+12なら12)。表示が読み取れなければnull",
        },
        "score": {"type": "integer", "description": "今回のプレーのEXスコア"},
        "score_diff_from_best": {
            "type": ["integer", "null"],
            "description": "自己ベストスコアとの差分(符号付き)。NEW RECORD等で差分表示が無ければnull",
        },
        "pgreat": {"type": "integer"},
        "great": {"type": "integer"},
        "good": {"type": "integer"},
        "bad": {"type": "integer"},
        "poor": {"type": "integer"},
        "miss_count": {"type": "integer", "description": "今回のプレーのミスカウント"},
        "miss_count_diff_from_best": {
            "type": ["integer", "null"],
            "description": "自己ベストミスカウントとの差分(符号付き)。NEW RECORD等で差分表示が無ければnull",
        },
        "is_new_score_record": {"type": "boolean"},
        "is_new_miss_record": {"type": "boolean"},
        "unclear_fields": {
            "type": "array",
            "items": {"type": "string"},
            "description": "反射・ブレ・切れなどで読み取りに自信が無いフィールド名の一覧(無ければ空配列)",
        },
    },
    "required": [
        "title",
        "artist",
        "mode",
        "difficulty",
        "level",
        "notes",
        "clear_type",
        "dj_level_rank",
        "dj_level_diff",
        "score",
        "score_diff_from_best",
        "pgreat",
        "great",
        "good",
        "bad",
        "poor",
        "miss_count",
        "miss_count_diff_from_best",
        "is_new_score_record",
        "is_new_miss_record",
        "unclear_fields",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
あなたはbeatmania IIDX INFINITASのリザルト画面の写真からプレー結果を抽出するアシスタントです。

画面はスマートフォン等でモニターを撮影した写真で、照明の反射や背景の写り込み、
斜めからの角度などノイズが含まれることがあります。ゲーム画面のUI要素だけを見て判断してください。

典型的なレイアウト:
- 画面下部中央付近に曲名・アーティスト名・難易度(BEGINNER/NORMAL/HYPER/ANOTHER/LEGGENDARIA)と
  難易度の数値、SP/DP、ノーツ数が表示されている
- 右側に「CLEAR TYPE」「DJ LEVEL」「SCORE」「MISS COUNT」が2列(ベストスコア/今回のスコア)で並ぶ。
  今回のプレー(右列、多くは水色/シアン文字)の値を使うこと
- DJ LEVELの右側の小さな数字(例: B+0012)はB等のランク基準点からの差分点数
- SCORE/MISS COUNTの列の下にある小さい数字は自己ベストとの差分。NEW RECORDの場合は差分が
  表示されないことがある
- 下部にJUDGE内訳(PGREAT/GREAT/GOOD/BAD/POOR)が円グラフと共に表示される

値が反射や画質で確信を持てない場合は、推測で埋めずにunclear_fieldsにそのフィールド名を入れてください。
"""


def encode_image(path: str) -> tuple[str, str]:
    media_type, _ = mimetypes.guess_type(path)
    if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise ValueError(f"対応していない画像形式です: {path} ({media_type})")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return media_type, data


def extract_from_image(client: anthropic.Anthropic, image_path: str) -> dict:
    media_type, image_data = encode_image(image_path)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": "この画像のリザルトを抽出してください。",
                    },
                ],
            }
        ],
    )

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


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


def build_history_row(data: dict, song, image_path: str, captured_at: str) -> dict:
    return {
        "取込日時": captured_at,
        "タイトル": song.title,
        "バージョン": song.version,
        "ジャンル": song.genre,
        "アーティスト": song.artist,
        "モード": data["mode"],
        "難易度": data["difficulty"],
        "難易度数値": data["level"],
        "ノーツ数": data["notes"] if data["notes"] is not None else "",
        "スコア": data["score"],
        "スコア自己ベスト差分": (
            data["score_diff_from_best"] if data["score_diff_from_best"] is not None else ""
        ),
        "PGreat": data["pgreat"],
        "Great": data["great"],
        "Good": data["good"],
        "Bad": data["bad"],
        "Poor": data["poor"],
        "ミスカウント": data["miss_count"],
        "ミスカウント自己ベスト差分": (
            data["miss_count_diff_from_best"]
            if data["miss_count_diff_from_best"] is not None
            else ""
        ),
        "クリアタイプ": data["clear_type"],
        "DJ LEVEL": data["dj_level_rank"],
        "DJ LEVEL基準点差分": (
            data["dj_level_diff"] if data["dj_level_diff"] is not None else ""
        ),
        "自己ベスト更新(スコア)": "Y" if data["is_new_score_record"] else "",
        "自己ベスト更新(ミスカウント)": "Y" if data["is_new_miss_record"] else "",
        "元画像": os.path.basename(image_path),
    }


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
            from song_match import SongRow

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
