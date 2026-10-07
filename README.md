# MVCI 配信情報フィード（テスト版）

YouTubeの公開チャンネルRSSからMVCI関連タイトルの最新動画を選び、ページ、RSS 2.0、JSONを生成します。YouTube Data API OAuthを設定すると、YouTube APIで配信状態を確認し、対象プレイリストへ現在のRSS内の候補を追加して選択動画を先頭へ移します。動画の選択基準は引き続き「最新のMVCI関連動画」です。ライブ状態によって古い動画へ切り替えることはありません。

RSSの動画タイトルには状態が付きます。配信中をAPIで確認できた時だけ `配信中！｜`、配信中ではない時は `直近のMVCI配信｜`、API確認できない場合は `配信状態を確認できません｜` です。ライブ状態は `videos.list` の `liveBroadcastContent=live` かつ `actualEndTime` が無い場合だけ配信中とし、APIエラーや不明な値は不明のまま扱います。YouTube RSSの公開日時はライブ開始時刻ではありません。

このページ自体はGitHub Pagesの静的ページです。Wikiの固定見出しを自動で書き換えることはできません。Wikiの見出しは「配信情報」のような汎用表現にして、以下のRSS表示を既存のプレイヤー埋め込みより上に置いてください。RSSが状態ラベルを配信ごとに付けます。

## 最初に登録されているチャンネル

設定済みは **Ororo n**（`UCbZogYHnnzt7JxHoO8TDvpg`）と **机上の空論**（`UC7kwcBnPAI39I56s10yuQzQ`）です。Cyber（`UCGWb15jpJU25Gx_ckDcF0Ew`）は停止中として無効です。ほかの候補は `config.json` にID未設定・無効で入っています。YouTubeのチャンネルURLに `/channel/UC...` がある場合は、表示されたIDを `id` に設定し `enabled` を `true` にします。ハンドル名からIDを推測しないでください。

## GitHub Pagesへアップロード

1. GitHubで公開リポジトリ `MVCIinfo/mvci-live-feed` を開きます。まだ無ければ同名の公開リポジトリを作ります。このパッケージは既存リポジトリを更新する場合にも使えます。
2. **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にします。
3. リポジトリのトップに `build.py`、`youtube_api.py`、`config.json`、`README.md`、`.gitignore`、`tests/`、`tools/`、`WIKIWIKI-snippet.txt` をアップロードまたは置き換えます。既に独自に追加したチャンネル設定がある場合は、`config.json`を上書きする前に `channels` の項目を新しい設定へ移してください。隠し `.github` フォルダーは次の手順で更新します。
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

workflowは15分間隔です。1回ごとに最新動画状態を確認し、RSSで取得できたMVCI関連動画を候補にしてプレイリストを重複なしで同期します。削除は行いません。新規追加は1回あたり最大10件で、選択中の最新動画を追加枠で優先します。過去動画全体を検索することはなく、各チャンネルRSSの最近の動画だけが対象です。

YouTube Data APIの標準割当は通常その他のAPI操作で1日10,000ユニットで、プレイリストへの1件挿入は50ユニットです。新規動画の追加が集中すると割当を消費するため、追加上限を `config.json` の `max_playlist_additions_per_run` で調整してください。API割当の変更があればGoogle Cloud Consoleと[公式クォータ資料](https://developers.google.com/youtube/v3/determine_quota_cost)で確認してください。[playlistItems.insertの仕様と手動順序の要件](https://developers.google.com/youtube/v3/docs/playlistItems/insert)

## ローカル確認

Python 3の標準ライブラリだけで動きます。フィクスチャテストはネットワークにもOAuthにも接続しません。

```sh
python -m unittest discover -s tests -v
python build.py
```

OAuth設定をしないローカル実行ではAPI連携を行いません。実際の認証やYouTubeプレイリスト編集はこのパッケージ作成時には実行していません。
