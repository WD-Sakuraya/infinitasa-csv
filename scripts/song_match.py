"""OCR/画像解析で読み取ったタイトルを data/song_db.csv のTITLEに突合する。"""
import csv
import difflib
from dataclasses import dataclass


@dataclass
class SongRow:
    version: str
    title: str
    genre: str
    artist: str


@dataclass
class MatchCandidate:
    song: SongRow
    score: float


def load_song_db(path: str) -> list[SongRow]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [
            SongRow(
                version=row["バージョン"],
                title=row["タイトル"],
                genre=row["ジャンル"],
                artist=row["アーティスト"],
            )
            for row in reader
        ]


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_candidates(
    ocr_title: str, songs: list[SongRow], top_n: int = 5
) -> list[MatchCandidate]:
    scored = [
        MatchCandidate(song=s, score=_similarity(ocr_title, s.title)) for s in songs
    ]
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:top_n]


# 類似度がこの値以上、かつ2位候補とこれだけ差があれば自動採用する
AUTO_ACCEPT_MIN_SCORE = 0.92
AUTO_ACCEPT_MIN_MARGIN = 0.08


def resolve_title(
    ocr_title: str, songs: list[SongRow], top_n: int = 5
) -> tuple[SongRow | None, list[MatchCandidate]]:
    """自動採用できればその曲を返す。怪しい場合は (None, 候補一覧) を返す。"""
    candidates = find_candidates(ocr_title, songs, top_n=top_n)
    if not candidates:
        return None, []

    top = candidates[0]
    second_score = candidates[1].score if len(candidates) > 1 else 0.0

    if top.score >= AUTO_ACCEPT_MIN_SCORE and (
        top.score - second_score >= AUTO_ACCEPT_MIN_MARGIN or len(candidates) == 1
    ):
        return top.song, candidates

    return None, candidates
