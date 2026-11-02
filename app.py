"""infinitasa CSV のプレー履歴を見るStreamlitアプリ。

起動:
    streamlit run app.py
"""
import csv
import glob
import os

import altair as alt
import pandas as pd
import streamlit as st

HISTORY_PATH = "data/history.csv"

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


def main() -> None:
    st.set_page_config(page_title="INFINITAS スコア履歴", layout="wide")
    st.title("INFINITAS スコア履歴")

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
