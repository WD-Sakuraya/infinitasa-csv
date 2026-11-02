"""リザルト画像からのデータ抽出ロジック(CLIスクリプトとStreamlitアプリの共通部分)。"""
import base64
import json
import mimetypes
import os

import anthropic

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

SUPPORTED_MEDIA_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")


def extract_from_bytes(client: anthropic.Anthropic, image_bytes: bytes, media_type: str) -> dict:
    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise ValueError(f"対応していない画像形式です: {media_type}")

    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

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


def extract_from_image(client: anthropic.Anthropic, image_path: str) -> dict:
    media_type, _ = mimetypes.guess_type(image_path)
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    return extract_from_bytes(client, image_bytes, media_type or "")


def build_history_row(data: dict, song, image_name: str, captured_at: str) -> dict:
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
        "元画像": os.path.basename(image_name),
    }
