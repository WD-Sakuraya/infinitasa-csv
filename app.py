"""infinitasa CSV のプレー履歴を見るStreamlitアプリ。

起動:
    streamlit run app.py
"""
import csv
import datetime
import glob
import os

import altair as alt
import anthropic
import pandas as pd
import streamlit as st

from scripts.iidx_extract import build_history_row, extract_from_bytes
from scripts.song_match import SongRow, load_song_db, resolve_title

HISTORY_PATH = "data/history.csv"
SONG_DB_PATH = "data/song_db.csv"

# 履歴データ(data/history.csv)がまだ無い場合、既存の集計形式CSV
# (1曲1行・自己ベストのみ、例: 2253-2531_sp_score.csv)を探して代わりに表示する。
LEGACY_REQUIRED_COLUMNS = {"バージョン", "タイトル", "最終プレー日時"}
LEGACY_NUMERIC_SUFFIXES = ["難易度", "スコア", "PGreat", "Great", "ミスカウント"]
LEGACY_TEXT_SUFFIXES = ["クリアタイプ", "DJ LEVEL"]

DIFFICULTIES = ["BEGINNER", "NORMAL", "HYPER", "ANOTHER", "LEGGENDARIA"]
# dataviz skillの既定カテゴリカルパレット(slot1-5)を難易度の並びに固定で割り当てる。
# フィルタで表示される難易度が変わっても色は常に同じ難易度に対応する。
DIFFICULTY_COLORS = {
    "BEGINNER": "#008300",
    "NORMAL": "#2a78d6",
    "HYPER": "#eda100",
    "ANOTHER": "#e34948",
    "LEGGENDARIA": "#6250d6",
}

NUMERIC_COLUMNS = [
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
    "DJ LEVEL基準点差分",
]


def process_history_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["取込日時"] = pd.to_datetime(df["取込日時"])
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@st.cache_data
def load_history(path: str) -> pd.DataFrame:
    return process_history_df(pd.read_csv(path, encoding="utf-8-sig"))


def difficulty_color_scale(present: list[str]) -> alt.Scale:
    return alt.Scale(
        domain=DIFFICULTIES,
        range=[DIFFICULTY_COLORS[d] for d in DIFFICULTIES],
    )


def find_legacy_csvs(root: str = ".") -> list[str]:
    candidates = []
    for path in sorted(glob.glob(os.path.join(root, "*.csv"))):
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f))
        except (StopIteration, OSError, UnicodeDecodeError):
            continue
        if LEGACY_REQUIRED_COLUMNS.issubset(set(header)):
            candidates.append(path)
    return candidates


def process_legacy_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for d in DIFFICULTIES:
        for suf in LEGACY_NUMERIC_SUFFIXES:
            col = f"{d} {suf}"
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    if "プレー回数" in df.columns:
        df["プレー回数"] = pd.to_numeric(df["プレー回数"], errors="coerce")
    return df


@st.cache_data
def load_legacy_summary(path: str) -> pd.DataFrame:
    return process_legacy_df(pd.read_csv(path, encoding="utf-8-sig"))


def detect_csv_format(columns: set[str]) -> str | None:
    """アップロードされたCSVの列構成から 'history' / 'legacy' / None(不明) を判定する。"""
    if {"取込日時", "難易度"}.issubset(columns) and "タイトル" in columns:
        return "history"
    if LEGACY_REQUIRED_COLUMNS.issubset(columns):
        return "legacy"
    return None


def melt_legacy(wide_df: pd.DataFrame) -> pd.DataFrame:
    base_cols = ["バージョン", "タイトル", "ジャンル", "アーティスト", "プレー回数", "最終プレー日時"]
    parts = []
    for d in DIFFICULTIES:
        rename_map = {f"{d} {suf}": suf for suf in LEGACY_NUMERIC_SUFFIXES[1:] + LEGACY_TEXT_SUFFIXES}
        rename_map[f"{d} 難易度"] = "難易度数値"
        cols = base_cols + list(rename_map.keys())
        sub = wide_df[cols].rename(columns=rename_map).copy()
        sub["難易度"] = d
        parts.append(sub)
    long_df = pd.concat(parts, ignore_index=True)
    long_df["難易度"] = pd.Categorical(long_df["難易度"], categories=DIFFICULTIES, ordered=True)
    return long_df


def render_song_tab(df: pd.DataFrame) -> None:
    titles = sorted(df["タイトル"].unique())
    title = st.selectbox("曲を選択", titles)

    song_df = df[df["タイトル"] == title].sort_values("取込日時")
    available_diffs = [d for d in DIFFICULTIES if d in song_df["難易度"].unique()]
    selected_diffs = st.multiselect(
        "表示する難易度", available_diffs, default=available_diffs
    )
    plot_df = song_df[song_df["難易度"].isin(selected_diffs)]

    if plot_df.empty:
        st.info("表示する難易度を選択してください。")
        return

    st.caption(f"{plot_df['アーティスト'].iloc[0]} / {plot_df['バージョン'].iloc[0]}")

    color = alt.Color(
        "難易度:N",
        scale=difficulty_color_scale(selected_diffs),
        sort=DIFFICULTIES,
        legend=alt.Legend(title="難易度"),
    )

    score_chart = (
        alt.Chart(plot_df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("取込日時:T", title="取込日時"),
            y=alt.Y("スコア:Q", title="スコア"),
            color=color,
            tooltip=[
                alt.Tooltip("取込日時:T", title="取込日時"),
                alt.Tooltip("難易度:N"),
                alt.Tooltip("スコア:Q"),
                alt.Tooltip("クリアタイプ:N"),
                alt.Tooltip("DJ LEVEL:N"),
                alt.Tooltip("ミスカウント:Q"),
            ],
        )
        .properties(height=300, title="スコア推移")
    )
    st.altair_chart(score_chart, width="stretch")

    miss_chart = (
        alt.Chart(plot_df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("取込日時:T", title="取込日時"),
            y=alt.Y("ミスカウント:Q", title="ミスカウント"),
            color=color,
            tooltip=[
                alt.Tooltip("取込日時:T", title="取込日時"),
                alt.Tooltip("難易度:N"),
                alt.Tooltip("ミスカウント:Q"),
            ],
        )
        .properties(height=260, title="ミスカウント推移")
    )
    st.altair_chart(miss_chart, width="stretch")

    st.subheader("プレー履歴(詳細)")
    display_cols = [
        "取込日時",
        "難易度",
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
    ]
    st.dataframe(
        plot_df[display_cols].sort_values("取込日時", ascending=False),
        width="stretch",
        hide_index=True,
    )


def render_overview_tab(df: pd.DataFrame) -> None:
    best = (
        df.sort_values("スコア", ascending=False)
        .groupby(["タイトル", "難易度"], as_index=False)
        .first()
    )
    play_counts = (
        df.groupby("タイトル", as_index=False)
        .size()
        .rename(columns={"size": "プレー回数"})
    )
    last_played = (
        df.groupby("タイトル", as_index=False)["取込日時"]
        .max()
        .rename(columns={"取込日時": "最終プレー日時"})
    )

    overview = best.merge(play_counts, on="タイトル").merge(last_played, on="タイトル")
    overview = overview.sort_values("最終プレー日時", ascending=False)

    display_cols = [
        "タイトル",
        "バージョン",
        "ジャンル",
        "アーティスト",
        "難易度",
        "スコア",
        "クリアタイプ",
        "DJ LEVEL",
        "ミスカウント",
        "プレー回数",
        "最終プレー日時",
    ]
    st.dataframe(overview[display_cols], width="stretch", hide_index=True)


def render_recent_tab(df: pd.DataFrame) -> None:
    n = st.slider("表示件数", min_value=10, max_value=200, value=50, step=10)
    recent = df.sort_values("取込日時", ascending=False).head(n)
    display_cols = [
        "取込日時",
        "タイトル",
        "難易度",
        "スコア",
        "スコア自己ベスト差分",
        "ミスカウント",
        "クリアタイプ",
        "DJ LEVEL",
        "自己ベスト更新(スコア)",
        "自己ベスト更新(ミスカウント)",
    ]
    st.dataframe(recent[display_cols], width="stretch", hide_index=True)


def render_legacy_view(wide_df: pd.DataFrame) -> None:
    long_df = melt_legacy(wide_df)
    # 「クリアタイプ」はNO PLAY以外でもスコア0のまま埋まっている行があるため、
    # プレー済みかどうかはスコア>0を基準に判定する。
    played = long_df[long_df["スコア"] > 0]

    col1, col2, col3 = st.columns(3)
    col1.metric("収録曲数", len(wide_df))
    col2.metric("プレー済み難易度数", len(played))
    col3.metric("最終プレー日時", str(wide_df["最終プレー日時"].max()))

    tab_overview, tab_song = st.tabs(["曲一覧", "曲ごとの自己ベスト"])

    with tab_overview:
        query = st.text_input("曲名で検索(部分一致)")
        only_played = st.checkbox("プレー済みの難易度のみ表示", value=True)
        view = played if only_played else long_df
        if query:
            view = view[view["タイトル"].str.contains(query, case=False, na=False)]
        display_cols = [
            "タイトル", "バージョン", "ジャンル", "アーティスト", "難易度",
            "難易度数値", "スコア", "クリアタイプ", "DJ LEVEL", "ミスカウント",
            "プレー回数", "最終プレー日時",
        ]
        st.dataframe(
            view[display_cols].sort_values(["タイトル", "難易度"]),
            width="stretch",
            hide_index=True,
        )

    with tab_song:
        titles = sorted(wide_df["タイトル"].unique())
        title = st.selectbox("曲を選択", titles)
        song_long = played[played["タイトル"] == title].sort_values("難易度")

        if song_long.empty:
            st.info("この曲にはプレー済みの難易度がありません。")
            return

        st.caption(f"{song_long['アーティスト'].iloc[0]} / {song_long['バージョン'].iloc[0]}")

        color = alt.Color(
            "難易度:N",
            scale=difficulty_color_scale(DIFFICULTIES),
            sort=DIFFICULTIES,
            legend=alt.Legend(title="難易度"),
        )
        bar = (
            alt.Chart(song_long)
            .mark_bar()
            .encode(
                x=alt.X("難易度:N", sort=DIFFICULTIES, title="難易度"),
                y=alt.Y("スコア:Q", title="スコア(自己ベスト)"),
                color=color,
                tooltip=[
                    alt.Tooltip("難易度:N"),
                    alt.Tooltip("スコア:Q"),
                    alt.Tooltip("クリアタイプ:N"),
                    alt.Tooltip("DJ LEVEL:N"),
                    alt.Tooltip("ミスカウント:Q"),
                ],
            )
            .properties(height=300, title="難易度別スコア(自己ベスト)")
        )
        st.altair_chart(bar, width="stretch")

        display_cols = ["難易度", "難易度数値", "スコア", "PGreat", "Great", "ミスカウント", "クリアタイプ", "DJ LEVEL"]
        st.dataframe(song_long[display_cols], width="stretch", hide_index=True)


def get_anthropic_api_key() -> str | None:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY")


@st.cache_data
def load_song_db_cached(path: str):
    if not os.path.exists(path):
        return None
    return load_song_db(path)


def render_convert_page() -> None:
    st.header("リザルト画像から変換")

    api_key = get_anthropic_api_key()
    if not api_key:
        st.error(
            "ANTHROPIC_API_KEYが設定されていません。\n\n"
            "- Streamlit Community Cloudの場合: アプリ管理画面の "
            "**Settings → Secrets** に `ANTHROPIC_API_KEY = \"sk-ant-...\"` を追加してください。\n"
            "- ローカル実行の場合: 環境変数 `ANTHROPIC_API_KEY` を設定してください。"
        )
        return

    songs = load_song_db_cached(SONG_DB_PATH)
    if songs is None:
        st.error(f"楽曲データベース({SONG_DB_PATH})が見つかりません。")
        return

    client = anthropic.Anthropic(api_key=api_key)

    if "convert_rows" not in st.session_state:
        st.session_state.convert_rows = []
    if "pending_images" not in st.session_state:
        st.session_state.pending_images = {}

    uploaded_images = st.file_uploader(
        "リザルト画面の画像を選択(複数可)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="convert_image_uploader",
    )
    captured_date = st.date_input("取込日時として記録する日付", value=datetime.date.today())

    if uploaded_images and st.button("選択した画像を解析する"):
        for img in uploaded_images:
            if img.name in st.session_state.pending_images:
                continue
            with st.spinner(f"{img.name} を解析中..."):
                try:
                    data = extract_from_bytes(client, img.getvalue(), img.type or "image/jpeg")
                except Exception as e:
                    st.error(f"{img.name} の解析に失敗しました: {e}")
                    continue
            song, candidates = resolve_title(data["title"], songs)
            st.session_state.pending_images[img.name] = {
                "data": data,
                "song": song,
                "candidates": candidates,
            }

    for name, item in list(st.session_state.pending_images.items()):
        data = item["data"]
        resolved = item["song"] is not None
        with st.expander(
            f"{name} — {data['title']} ({data['difficulty']} / スコア{data['score']})",
            expanded=not resolved,
        ):
            if data["unclear_fields"]:
                st.warning(f"読み取りに自信が無い項目: {', '.join(data['unclear_fields'])}")

            if item["song"] is not None:
                resolved_song = item["song"]
                st.caption(f"{resolved_song.title} / {resolved_song.artist} ({resolved_song.version})")
            else:
                options = [
                    f"{c.song.title} / {c.song.artist} ({c.song.version})" for c in item["candidates"]
                ]
                options.append("候補になし(手入力する)")
                choice = st.radio("曲を選択してください", options, key=f"choice_{name}")
                if choice == options[-1]:
                    manual_title = st.text_input("正しいタイトルを入力", key=f"manual_{name}")
                    match = next((s for s in songs if s.title == manual_title), None)
                    resolved_song = match or (
                        SongRow(version="", title=manual_title, genre="", artist=data["artist"])
                        if manual_title
                        else None
                    )
                else:
                    idx = options.index(choice)
                    resolved_song = item["candidates"][idx].song

            col1, col2 = st.columns(2)
            add_disabled = resolved_song is None or not getattr(resolved_song, "title", None)
            if col1.button("この内容で追加", key=f"add_{name}", disabled=add_disabled):
                row = build_history_row(
                    data, resolved_song, name, captured_date.strftime("%Y-%m-%d")
                )
                st.session_state.convert_rows.append(row)
                del st.session_state.pending_images[name]
                st.rerun()
            if col2.button("この画像をスキップ", key=f"skip_{name}"):
                del st.session_state.pending_images[name]
                st.rerun()

    render_accumulated_rows_section()


def render_accumulated_rows_section() -> None:
    """画像変換・手動入力どちらで追加した行も、ここで一覧表示してCSVダウンロードできる。"""
    if not st.session_state.get("convert_rows"):
        return

    st.subheader("追加済みの履歴")
    result_df = pd.DataFrame(st.session_state.convert_rows)
    st.dataframe(result_df, width="stretch", hide_index=True)

    existing_upload = st.file_uploader(
        "(任意) 既存のhistory.csvに追記する場合はアップロード",
        type="csv",
        key="existing_history_upload",
    )
    if existing_upload is not None:
        existing_df = pd.read_csv(existing_upload, encoding="utf-8-sig")
        combined_df = pd.concat([existing_df, result_df], ignore_index=True)
    else:
        combined_df = result_df

    csv_bytes = combined_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "CSVをダウンロード",
        data=csv_bytes,
        file_name="history.csv",
        mime="text/csv",
    )

    if st.button("追加済み履歴をクリア"):
        st.session_state.convert_rows = []
        st.rerun()


CLEAR_TYPES = [
    "NO PLAY",
    "FAILED",
    "ASSIST CLEAR",
    "EASY CLEAR",
    "CLEAR",
    "HARD CLEAR",
    "EX HARD CLEAR",
    "FULLCOMBO CLEAR",
]
DJ_LEVEL_RANKS = ["F", "E", "D", "C", "B", "A", "AA", "AAA"]


def _parse_optional_int(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def render_manual_entry_page() -> None:
    st.header("手動で入力してCSVに追加")

    songs = load_song_db_cached(SONG_DB_PATH)
    if songs is None:
        st.error(f"楽曲データベース({SONG_DB_PATH})が見つかりません。")
        return

    if "convert_rows" not in st.session_state:
        st.session_state.convert_rows = []

    titles = sorted(s.title for s in songs)
    title_options = ["(一覧に無い・手入力する)"] + titles
    title_choice = st.selectbox("曲名(検索可)", title_options, key="manual_title_select")

    if title_choice == title_options[0]:
        manual_title = st.text_input("曲名を入力", key="manual_title_text")
        manual_artist = st.text_input("アーティスト名を入力", key="manual_artist_text")
        song = (
            SongRow(version="", title=manual_title, genre="", artist=manual_artist)
            if manual_title
            else None
        )
    else:
        song = next(s for s in songs if s.title == title_choice)
        st.caption(f"{song.artist} / {song.genre} / {song.version}")

    with st.form("manual_entry_form"):
        col1, col2, col3 = st.columns(3)
        mode = col1.radio("モード", ["SP", "DP"], horizontal=True)
        difficulty = col2.selectbox("難易度", DIFFICULTIES)
        level = col3.number_input("難易度数値", min_value=0, max_value=12, step=1, value=0)

        col1, col2 = st.columns(2)
        clear_type = col1.selectbox("クリアタイプ", CLEAR_TYPES)
        dj_level_rank = col2.selectbox("DJ LEVEL", DJ_LEVEL_RANKS, index=4)

        col1, col2, col3 = st.columns(3)
        score = col1.number_input("スコア", min_value=0, step=1, value=0)
        miss_count = col2.number_input("ミスカウント", min_value=0, step=1, value=0)
        notes = col3.text_input("ノーツ数(任意)", value="")

        col1, col2 = st.columns(2)
        score_diff = col1.text_input("スコア自己ベスト差分(任意、符号付き)", value="")
        miss_diff = col2.text_input("ミスカウント自己ベスト差分(任意、符号付き)", value="")
        dj_level_diff = st.text_input("DJ LEVEL基準点差分(任意、符号付き)", value="")

        st.caption("JUDGE内訳")
        col1, col2, col3, col4, col5 = st.columns(5)
        pgreat = col1.number_input("PGreat", min_value=0, step=1, value=0)
        great = col2.number_input("Great", min_value=0, step=1, value=0)
        good = col3.number_input("Good", min_value=0, step=1, value=0)
        bad = col4.number_input("Bad", min_value=0, step=1, value=0)
        poor = col5.number_input("Poor", min_value=0, step=1, value=0)

        col1, col2 = st.columns(2)
        is_new_score_record = col1.checkbox("自己ベスト更新(スコア)")
        is_new_miss_record = col2.checkbox("自己ベスト更新(ミスカウント)")

        captured_date = st.date_input("取込日時として記録する日付", value=datetime.date.today())

        submitted = st.form_submit_button("この内容を追加")

    if submitted:
        if song is None or not song.title:
            st.error("曲名を選択または入力してください。")
            return

        data = {
            "mode": mode,
            "difficulty": difficulty,
            "level": int(level),
            "notes": _parse_optional_int(notes),
            "clear_type": clear_type,
            "dj_level_rank": dj_level_rank,
            "dj_level_diff": _parse_optional_int(dj_level_diff),
            "score": int(score),
            "score_diff_from_best": _parse_optional_int(score_diff),
            "pgreat": int(pgreat),
            "great": int(great),
            "good": int(good),
            "bad": int(bad),
            "poor": int(poor),
            "miss_count": int(miss_count),
            "miss_count_diff_from_best": _parse_optional_int(miss_diff),
            "is_new_score_record": is_new_score_record,
            "is_new_miss_record": is_new_miss_record,
        }
        row = build_history_row(data, song, "手入力", captured_date.strftime("%Y-%m-%d"))
        st.session_state.convert_rows.append(row)
        st.success(f"「{song.title}」({difficulty})を追加しました。")

    render_accumulated_rows_section()


def main() -> None:
    st.set_page_config(page_title="INFINITAS スコア履歴", layout="wide")
    st.title("INFINITAS スコア履歴")

    mode = st.sidebar.radio("モード", ["履歴を見る", "リザルト画像から変換", "手動で入力"])
    if mode == "リザルト画像から変換":
        render_convert_page()
        return
    if mode == "手動で入力":
        render_manual_entry_page()
        return

    uploaded = st.file_uploader(
        "CSVファイルを選択(省略時はこのPC上のdata/history.csvや集計CSVを自動検出します)",
        type="csv",
    )
    if uploaded is not None:
        try:
            raw_df = pd.read_csv(uploaded, encoding="utf-8-sig")
        except Exception as e:
            st.error(f"CSVの読み込みに失敗しました: {e}")
            return

        fmt = detect_csv_format(set(raw_df.columns))
        if fmt == "history":
            df = process_history_df(raw_df)
            col1, col2, col3 = st.columns(3)
            col1.metric("総プレー回数", len(df))
            col2.metric("収録曲数", df["タイトル"].nunique())
            col3.metric("最終プレー日時", df["取込日時"].max().strftime("%Y-%m-%d %H:%M"))

            tab_song, tab_overview, tab_recent = st.tabs(
                ["曲ごとの推移", "全体一覧(自己ベスト)", "最近のプレー"]
            )
            with tab_song:
                render_song_tab(df)
            with tab_overview:
                render_overview_tab(df)
            with tab_recent:
                render_recent_tab(df)
        elif fmt == "legacy":
            render_legacy_view(process_legacy_df(raw_df))
        else:
            st.error(
                "このCSVの形式を認識できませんでした。"
                "history.csv形式(取込日時・難易度列を含む)か、"
                "集計CSV形式(バージョン・タイトル・最終プレー日時列を含む)のファイルを選択してください。"
            )
        return

    if not os.path.exists(HISTORY_PATH):
        legacy_candidates = find_legacy_csvs()
        if not legacy_candidates:
            st.warning(
                f"履歴データ({HISTORY_PATH})が見つかりません。\n\n"
                "先に `python scripts/extract_result.py <画像ファイル>` を実行してリザルト画像を取り込んでください。"
            )
            return

        st.info(
            "プレー単位の履歴データ(data/history.csv)はまだ無いため、"
            "既存の集計CSVを表示しています。プレー単位の推移グラフはhistory.csv作成後に利用できます。"
        )
        if len(legacy_candidates) > 1:
            legacy_path = st.selectbox("表示するCSVファイル", legacy_candidates)
        else:
            legacy_path = legacy_candidates[0]
            st.caption(f"読み込み中: {legacy_path}")

        wide_df = load_legacy_summary(legacy_path)
        render_legacy_view(wide_df)
        return

    df = load_history(HISTORY_PATH)

    col1, col2, col3 = st.columns(3)
    col1.metric("総プレー回数", len(df))
    col2.metric("収録曲数", df["タイトル"].nunique())
    col3.metric("最終プレー日時", df["取込日時"].max().strftime("%Y-%m-%d %H:%M"))

    tab_song, tab_overview, tab_recent = st.tabs(
        ["曲ごとの推移", "全体一覧(自己ベスト)", "最近のプレー"]
    )
    with tab_song:
        render_song_tab(df)
    with tab_overview:
        render_overview_tab(df)
    with tab_recent:
        render_recent_tab(df)


if __name__ == "__main__":
    main()
