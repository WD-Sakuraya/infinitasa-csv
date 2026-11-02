# infinitasa CSV

## プロジェクト概要
beatmania IIDX INFINITASのリザルト画面のスクリーンショットを読み取り、プレー結果をCSVファイルに保存するシステムを構築する。

## 目的
- リザルト画面の画像(スコア、PGreat/Great数、ミスカウント、クリアタイプ、DJ LEVELなど)をOCR等で解析
- 解析結果を既存のSPスコアCSV形式に沿って出力・追記する

## 現状
- サンプルとして `2253-2531_sp_score.csv`(目標とする集計データの出力フォーマット例)、`image.jpg`(リザルト画面の写真サンプル)が存在する
- 楽曲DB取り込みスクリプト `scripts/build_song_db.py` を実装済み(bemaniwikiをパースし `data/song_db.csv` を生成)
- リザルト画像解析スクリプト `scripts/extract_result.py` を実装済み(Claude Vision APIで画像を解析し `data/history.csv` に追記)。未着手: 集計CSV生成、複数枚一括取り込みの入力フロー

## 実行環境
- Python 3.15、依存パッケージ: `requests`, `beautifulsoup4`, `anthropic`, `streamlit`, `altair`, `pandas`(`requirements.txt`に記載)
- 画像解析には Anthropic API を使用(`ANTHROPIC_API_KEY` 環境変数が必要)
- Git/GitHub CLIはこのPCに未インストールだったため、winget経由でインストール済み

## デプロイ(履歴ビューアーの公開)
- GitHubリポジトリ: https://github.com/WD-Sakuraya/infinitasa-csv (Public。`.gitignore`で `/data/`, `*.csv`, `image*` を除外し個人データは非公開)
- Streamlit Community Cloudで公開中: https://infinitasa-csv-kx4p6gyyvnnzsjqvgdeuve.streamlit.app/ (ログイン不要でアクセス可能、シークレットウィンドウで確認済み)
- 公開アプリはローカルのdata/フォルダを読めないため、`app.py`のCSVアップローダーからその都度CSVファイルを選択して閲覧する運用
- `app.py`を更新した場合は `git add . && git commit && git push` すればCloud側に自動反映される(mainブランチ追従)

## データ構造(2本立て)
スコアの推移を追えるようにするため、以下の2種類のデータを管理する。

### 1. 履歴データ(新規・プレー単位)
リザルト写真を1枚取り込むごとに1行追加するログ形式。その回のプレーの値をそのまま記録する。

想定列: タイトル, 難易度(BEGINNER/NORMAL/HYPER/ANOTHER/LEGGENDARIA), 難易度数値, スコア, PGreat, Great, ミスカウント, クリアタイプ, DJ LEVEL(ランク), DJ LEVEL基準点からの差分, 自己ベストとの差分(スコア/ミスカウント), 取込日時

- **プレー回数**: この履歴データの該当曲×難易度の行数をカウントすれば算出できる
- **最終プレー日時**: 各行の「取込日時」(= システムが写真を受け取った日)
- **DJ LEVEL**: ランク文字(B/A/AA/AAA等)と、基準点からの差分点数(例: `B+0012`)を分けて記録。基準点は楽曲(ノーツ構成)ごとに異なる
- **PGreat/Great**: その回のプレーのJUDGE内訳をそのまま記録(自己ベスト時の内訳とは限らない)

### 2. 集計データ(既存形式・曲単位、参考: `2253-2531_sp_score.csv`)
1行目がヘッダー。1曲1行、各難易度の**自己ベストのみ**を保持する形式。履歴データから曲×難易度ごとにスコア最大の行を抽出して自動生成する。

- バージョン, タイトル, ジャンル, アーティスト, プレー回数
- 各難易度ごとに7列:
  - `{難易度} 難易度`, `{難易度} スコア`, `{難易度} PGreat`, `{難易度} Great`, `{難易度} ミスカウント`, `{難易度} クリアタイプ`, `{難易度} DJ LEVEL`
- 最終プレー日時

未プレーの難易度は `難易度=0, スコア=0, PGreat=0, Great=0, ミスカウント=---, クリアタイプ=NO PLAY, DJ LEVEL=---` となる(実データで確認済み。クリアタイプとDJ LEVELを当初逆に記載していたため訂正)。

注意: 実データ(`2253-2531_sp_score.csv`)には、スコア=0・DJ LEVEL=---・ミスカウント=---なのにクリアタイプだけ `ASSIST CLEAR` 等の実在するクリア名が入っている行がある(原因不明、データ側の仕様と思われる)。そのため「プレー済みかどうか」をクリアタイプの値だけで判定すると誤判定する。**スコア > 0 を基準に判定するのが安全。**(`app.py` の集計CSV表示はこの基準で実装済み)

- **バージョン / ジャンル**: 写真には表示されないため、楽曲データベース(`data/song_db.csv`)をタイトルで照合して補完する
- **タイトル**: OCRで読み取った文字列をそのまま使わず、`song_db.csv` のTITLEを正とする。OCR結果はこのTITLE一覧に対してあいまい一致で突合し、一致した正式なTITLE表記をCSVに記録する
  - 類似度が高く候補が1件に絞れる場合は自動採用
  - 複数候補が拮抗する/類似度が低く怪しいと判断した場合は自動採用せず、ユーザーに確認を求める

## 楽曲データベース
バージョン/ジャンルの照合元として bemaniwiki の「beatmania IIDX INFINITAS/全曲リスト」を使う。
- URL: https://bemaniwiki.com/?beatmania+IIDX+INFINITAS/%E5%85%A8%E6%9B%B2%E3%83%AA%E3%82%B9%E3%83%88
- 曲データは1つの大きな`<table>`内にあり、版ごとの見出し行(colspan行、例: `beatmania IIDX 5th style`)で曲がグルーピングされている。見出し行を順に追跡しながら曲行をパースし、バージョンを付与する
- 見出しテキストは「beatmania IIDX」プレフィックスと版番号を取り除いて正規化(例: `beatmania IIDX 11 IIDX RED` → `IIDX RED`)。番号と名前の間にスペースが無く単語がくっつくケース(`CANNONBALLERS`→`CANNON BALLERS`, `PinkyCrush`→`Pinky Crush`)は個別に補正している
- 曲行の列: 区分, SP難易度(BEGINNER/NORMAL/HYPER/ANOTHER/LEGGENDARIA), DP難易度(NORMAL/HYPER/ANOTHER/LEGGENDARIA), BPM, GENRE, TITLE, ARTIST
- 全体で約1895曲(取得時点、1st styleから現行バージョン+INFINITAS専用曲まで)

### scripts/build_song_db.py
- bemaniwikiのページを取得・パースし、`data/song_db.csv` に書き出す(列: バージョン, 区分, タイトル, ジャンル, アーティスト, SP/DP各難易度, BPM)
- `python scripts/build_song_db.py` でWebから取得、`--input <HTMLファイル>` でローカルHTMLを使ったテストも可能
- 動作確認済み: サンプル画像の曲(Digitank System → DJ TROOPERS / TECH-BREAKBEATS / DJ Mass MAD Izm*)、既存サンプルCSVの曲(Bad Routine, Don't be afraid myself 等)と一致

### scripts/iidx_extract.py (共通ロジック)
- リザルト画像からのデータ抽出ロジック本体(`extract_from_bytes` / `extract_from_image`, `HISTORY_COLUMNS`, `EXTRACTION_SCHEMA`, `SYSTEM_PROMPT`, `build_history_row`)。CLI(`extract_result.py`)とStreamlitアプリ(`app.py`)の両方から共通利用する
- Claude(`claude-opus-5-5`)のVision + 構造化出力(`output_config.format`のjson_schema)で、今回のプレー(今回のスコア列)の値を抽出:
  タイトル, アーティスト, モード(SP/DP), 難易度, 難易度数値, ノーツ数, クリアタイプ, DJ LEVELランク, DJ LEVEL基準点差分,
  スコア, スコア自己ベスト差分, PGreat/Great/Good/Bad/Poor, ミスカウント, ミスカウント自己ベスト差分, 自己ベスト更新フラグ
- 読み取りに自信が無いフィールドは `unclear_fields` として返させる

### scripts/extract_result.py (CLI)
- `python scripts/extract_result.py <画像ファイル...>` でリザルト画像を解析し、`data/history.csv` に1枚1行で追記する
- タイトルは `scripts/song_match.py`(`difflib`によるあいまい一致)で `data/song_db.csv` と突合。自動採用できない場合はCLIで候補を提示し、ユーザーに選択/手入力/スキップを求める
- `--song-db`, `--history`, `--date` オプションあり。`--date` 省略時は実行時点の日時を「取込日時」として記録
- `scripts/__init__.py` を追加し、`scripts`パッケージとして `app.py`(プロジェクト直下)からもimportできるようにしてある

### scripts/build_summary.py
- `python scripts/build_summary.py` で `data/history.csv` を集計し、`data/summary.csv` に書き出す(既存サンプル `2253-2531_sp_score.csv` と同じヘッダー・列構成)
- タイトルごとにグルーピングし、プレー回数=該当曲の履歴行数、各難易度は履歴内でスコア最大の行を自己ベストとして採用。未プレーの難易度は `難易度=0, スコア=0, PGreat=0, Great=0, ミスカウント=---, クリアタイプ=NO PLAY, DJ LEVEL=---` で埋める
- 曲の並び順は `data/song_db.csv` の出現順(≒バージョンの時系列順)に合わせる
- APIキー不要で単体テスト済み(手作りの履歴データで動作確認: 複数回プレーした曲のベストスコア抽出、プレー回数集計、最終プレー日時の算出が正しいことを確認)

### app.py (履歴ビューアー)
- `streamlit run app.py` で起動するローカルWebアプリ。`data/history.csv` を読み込んで表示する(無い場合は取り込み手順を案内するメッセージを表示)
- 3タブ構成:
  - 「曲ごとの推移」: 曲を選択(検索可)→難易度ごとのスコア推移・ミスカウント推移を折れ線グラフ(Altair)で表示、詳細テーブルも表示
  - 「全体一覧(自己ベスト)」: 曲×難易度ごとの自己ベスト・プレー回数・最終プレー日時の一覧
  - 「最近のプレー」: 直近N件の生履歴
- 難易度ごとの色は BEGINNER=緑, NORMAL=青, HYPER=黄, ANOTHER=赤, LEGGENDARIA=紫 に固定割り当て(ユーザー指定、dataviz既定パレットのslotを流用)。フィルタで表示難易度が変わっても同じ難易度は同じ色。スコア軸とミスカウント軸は別チャートに分離(dual-axis回避)
- `data/history.csv` が無い場合、プロジェクト直下にある既存形式の集計CSV(ヘッダーに バージョン/タイトル/最終プレー日時 を含むもの。例: `2253-2531_sp_score.csv`)を自動検出して読み込み専用で表示する(「曲一覧」「曲ごとの自己ベスト」の2タブ、推移グラフは無し、難易度別スコアの棒グラフのみ)
- 画面上部に `st.file_uploader` を常設。CSVをアップロードすると、ローカル自動検出より優先してそのファイルを表示する。列構成から history形式/legacy集計形式を自動判定(`detect_csv_format`)し、どちらでも無ければエラーメッセージを表示。他の端末のブラウザからアクセスした場合でも、そのCSVをアップロードすれば閲覧できる(リモートアクセス時にサーバー側PCのファイルパスに依存しない手段として追加)
- サイドバーの「モード」切り替えで「履歴を見る」/「リザルト画像から変換」を選べる

### リザルト画像から変換モード(app.py内, render_convert_page)
- サイトに画像をアップロードするだけで、ブラウザ上でCSV変換ができる機能。`scripts/iidx_extract.py`を直接importして使用
- APIキーは `st.secrets["ANTHROPIC_API_KEY"]`(Streamlit Cloudの場合: アプリ設定のSecretsに登録)または環境変数`ANTHROPIC_API_KEY`(ローカル実行の場合)から取得。未設定ならエラーメッセージを表示して案内
- 画像を複数選択→解析→曲名があいまい一致で自動解決できなければ候補をラジオボタンで選択(または手入力)→「この内容で追加」で `st.session_state.convert_rows` に蓄積
- Streamlit Cloudのファイルシステムは永続化されないため、サーバー側へのCSV書き込みはしない設計。変換結果はブラウザのセッション内に保持し、既存history.csvをアップロードして結合した上で「CSVをダウンロード」ボタンから取得する運用
- 楽曲DBは `data/song_db.csv` をリポジトリに同梱(公開データのため`.gitignore`で例外的に追跡対象にしている)
- AppTestで検証済み: APIキー未設定時のエラーメッセージ表示、モード切り替え(履歴を見る⇔変換)の往復でエラー無し。実際のAPI呼び出し(画像解析)はAPIキー未設定のためローカル未テスト
- `streamlit.testing.v1.AppTest` でヘッダレス動作確認済み。実データ(`2253-2531_sp_score.csv`、437曲)でも検証: 曲名検索、プレー済み難易度のみ表示、曲ごとの自己ベスト表示(quasar HYPER9 スコア1089等)、ファイルアップロード(history形式/legacy形式どちらも)まで一通りエラー無し。ブラウザでの目視確認は未実施

## 今後の検討事項
- 複数枚のスクリーンショットの入力方法(フォルダ監視/ドラッグ&ドロップなど、現状はコマンドライン引数指定のみ)
- extract_result.py のAPI呼び出し自体は未テスト(ANTHROPIC_API_KEY未設定のため)。キー取得後に実画像で動作確認が必要
- unclear_fieldsがある場合にユーザー確認を求めるフロー(現状は警告表示のみで値はそのまま記録)
- 既存CSVへの追記・更新ロジック(同じ曲・難易度の再プレー時の扱い、履歴は追記のみでよいか)
- song_db.csvの更新タイミング(bemaniwiki側の更新にどう追従するか)
- スマホアプリ化(バックエンド経由でClaude APIを呼ぶ構成への移行)
