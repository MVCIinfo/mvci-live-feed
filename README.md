# MVCI 配信情報フィード（テスト版）

YouTubeの公開チャンネルRSSからMVCI関連タイトルを選び、ページ、RSS 2.0、JSONを生成します。`MVCI 闘魂部` を含むタイトルは対象から除外します。ページ、RSS、JSONには有効チャンネル全体で公開日時が最も新しい1本を表示します。YouTube Data API OAuthを設定すると、プレイリストには各有効チャンネルの最新対象動画を1本ずつ同期し、全体で最も新しい選択動画を先頭に置きます。同じチャンネルの古い候補は追加しません。過去に登録済みの動画は削除しません。ライブ状態によって表示動画を切り替えることはありません。

既定の除外語は `config.json` の `exclude_keywords` で設定できます。項目が無い設定ファイルでは `MVCI 闘魂部` を使います。除外判定では大小文字と空白（半角/全角スペース、改行など）を無視します。`闘魂部` だけを含むタイトルや、`MVCI 決勝 闘魂部` のように語句の間に別の文字があるタイトルは、既定値だけでは除外しません。

チャンネルRSSが取得できない場合、OAuth設定済みならチャンネル情報からYouTube APIが返すアップロード用プレイリストIDを読み取り、最新15件の動画を読みます。これはチャンネルの全過去動画や全ライブ配信の検索ではありません。アップロード用IDを推測することはありません。RSS/API両方の取得に失敗した場合は既存のページを保ち、チャンネル名・公開チャンネルID・安全なエラー分類をActionsログに表示します。OAuth未設定時はAPI fallbackを使いません。

RSSの動画タイトルには状態が付きます。配信中をAPIで確認できた時だけ `配信中！｜`、配信中ではない時は `直近のMVCI配信｜`、API確認できない場合は `配信状態を確認できません｜` です。ライブ状態は `videos.list` の `liveBroadcastContent=live` かつ `actualEndTime` が無い場合だけ配信中とし、APIエラーや不明な値は不明のまま扱います。YouTube RSSの公開日時はライブ開始時刻ではありません。

このページ自体はGitHub Pagesの静的ページです。Wikiの固定見出しを自動で書き換えることはできません。Wikiの見出しは「配信情報」のような汎用表現にしてください。配信中バッジ、RSS状態ラベル、プレイヤーの順に置くWiki記述は `WIKIWIKI-snippet.txt` にあります。バッジはページ全体で選択された最新動画だけをAPIで配信中と確認できた場合に表示します。その他のチャンネル動画が配信中でも、バッジは表示しません。GitHub PagesやWiki側の画像キャッシュによって表示更新が遅れることがあります。

## 最初に登録されているチャンネル

設定済みは **Ororo n**（`UCbZogYHnnzt7JxHoO8TDvpg`）と **机上の空論**（`UC7kwcBnPAI39I56s10yuQzQ`）です。Cyber（`UCGWb15jpJU25Gx_ckDcF0Ew`）は停止中として無効です。ほかの候補は `config.json` にID未設定・無効で入っています。YouTubeのチャンネルURLに `/channel/UC...` がある場合は、表示されたIDを `id` に設定し `enabled` を `true` にします。ハンドル名からIDを推測しないでください。

## GitHub Pagesへアップロード

1. GitHubで公開リポジトリ `MVCIinfo/mvci-live-feed` を開きます。まだ無ければ同名の公開リポジトリを作ります。このパッケージは既存リポジトリを更新する場合にも使えます。
2. **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にします。
3. リポジトリのトップに `build.py`、`youtube_api.py`、`config.json`、`README.md`、`.gitignore`、`tests/`、`tools/`、`assets/`、`WIKIWIKI-snippet.txt` をアップロードまたは置き換えます。既に独自に追加したチャンネル設定がある場合は、`config.json`を上書きする前に `channels` の項目を新しい設定へ移してください。`exclude_keywords` が無い場合は標準値 `MVCI 闘魂部` を使います。隠し `.github` フォルダーは次の手順で更新します。
4. `.github/workflows/deploy.yml` が既にある場合は **Edit file** でこのパッケージの同パスにある内容へ置き換えます。まだ無ければ **Add file → Create new file** を選び、ファイル名に `.github/workflows/deploy.yml` を入力して内容を貼り付けます。
5. 初回は `Actions → Update and deploy MVCI feed → Run workflow` で手動実行します。以降は `main` への変更時と15分ごとに実行されます。Actionsの実行時刻やYouTube側の反映時刻には遅れがあるため、即時反映は保証されません。

## YouTube API連携（任意、実際のプレイリスト編集）

配信状態確認とプレイリスト同期には、プレイリスト `PLIA2oKVHJxPs` を編集できるGoogle/YouTubeアカウントの承認が必要です。別のアカウントのプレイリストを編集することはできません。まず対象アカウントでYouTube StudioまたはYouTubeから当該プレイリストを開き、編集権限と手動並べ替えができることを確かめてください。APIの挿入位置指定にはプレイリストの順序が手動設定である必要があります。

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクトを作成し、**YouTube Data API v3** を有効化します。
2. **Google Auth Platform / OAuth consent screen** を構成し、テスト運用なら利用するGoogleアカウントをテストユーザーに追加します。
3. **Credentials → Create credentials → OAuth client ID → Desktop app** からOAuthクライアントを作成し、JSONをダウンロードします。
4. このパッケージの `tools/authorize_youtube.py` をPython 3でローカル実行します。認証用ブラウザーを開いて、目的のプレイリスト所有アカウントで同意します。たとえば `python tools/authorize_youtube.py --client-json C:/private/client_secret.json --output C:/private/mvci-youtube-secrets.json` のように、入力と出力の両ファイルをリポジトリ外に置いてください。認証情報は表示されず、出力先にだけ保存されます。
5. GitHubリポジトリの **Settings → Secrets and variables → Actions → New repository secret** で、出力JSONの3値を各Secretに登録します。名前は `YOUTUBE_CLIENT_ID`、`YOUTUBE_CLIENT_SECRET`、`YOUTUBE_REFRESH_TOKEN` です。値を公開リポジトリ、Issue、Wiki、チャットに貼らないでください。
6. workflowを手動実行します。OAuth情報が全て無ければ動画状態は「配信状態を確認できません」となり、同期は無効です。3つのうち一部だけ設定するとビルドを止め、誤った状態のページを公開しません。プレイリスト同期に失敗した場合もページ公開を止めて、表示とプレイリストのずれを防ぎます。

Google OAuth同意画面が **Testing** の外部アプリでは、プロフィール系以外のスコープを使うrefresh tokenが7日で失効する場合があります。テスト期間中は再認証が必要になることがあります。継続運用前にGoogleの現行ルールと公開ステータスを確認してください。`youtube.force-ssl` は動画/プレイリスト情報へのアクセス権を含む広い権限です。同意画面で要求権限を必ず確認してください。[Google OAuth 2.0のrefresh token説明](https://developers.google.com/identity/protocols/oauth2)

## 更新頻度とクォータ

workflowは15分間隔です。1回ごとに全体で最も新しい動画の状態を確認し、プレイリストには各有効チャンネルの最新対象動画を1本ずつ同期します。全体の選択動画を先に追加し、先頭に置きます。追加上限 `max_playlist_additions_per_run` は1回に追加できる動画の最大数です。対象チャンネル数より小さい場合、他チャンネルの動画は後続実行に回ることがあります。既に登録された動画は重複追加せず、削除もしません。同一チャンネルの古い候補は追加しません。過去動画全体を検索することはなく、各チャンネルRSSやAPI fallbackの最近の動画だけが対象です。

YouTube Data APIの標準割当は通常その他のAPI操作で1日10,000ユニットで、プレイリストへの1件挿入は50ユニットです。新規動画の追加が集中すると割当を消費するため、追加上限を `config.json` の `max_playlist_additions_per_run` で調整してください。API割当の変更があればGoogle Cloud Consoleと[公式クォータ資料](https://developers.google.com/youtube/v3/determine_quota_cost)で確認してください。[playlistItems.insertの仕様と手動順序の要件](https://developers.google.com/youtube/v3/docs/playlistItems/insert)

同期後に選択動画が一覧に見つからない場合、読み取りを最大3回（待ち時間1秒、3秒）まで再試行します。先頭へ移動した場合も、位置0を読み取りで確認します。追加・移動操作そのものは再試行しないため、確認できない状態が続けば公開処理を止め、エラーにプレイリストID・動画ID・今回追加したか・上限値を表示します。この再確認は遅延の原因を特定するものではありません。選択動画が未登録で `max_playlist_additions_per_run` が0以下の場合は、書き込み前に設定を1以上にするようエラーを表示します。既に登録済みの選択動画は追加上限0でも位置確認できます。

## ローカル確認

Python 3の標準ライブラリだけで動きます。フィクスチャテストはネットワークにもOAuthにも接続しません。

```sh
python -m unittest discover -s tests -v
python build.py
```

OAuth設定をしないローカル実行ではAPI連携を行いません。実際の認証やYouTubeプレイリスト編集はこのパッケージ作成時には実行していません。

## 保守・更新手順

チャンネル設定、除外語、GitHub Actions、YouTube連携、Wiki表示の更新方法は[保守・更新手順](OPERATIONS.md)を参照してください。

