# MVCI 最新動画フィード（テスト版）

YouTube Data APIキーを使わず、公開されているチャンネルRSSを定期取得して、タイトルにMVCI関連語を含む最新動画を表示する静的ページです。YouTubeのRSSで取得できる各チャンネルの最近の動画だけを対象にするため、過去動画をすべて検索する仕組みではありません。

初期設定で取得するのは **Ororo n** と **机上の空論** の2チャンネルです。現在の設定は次のチャンネルIDを有効にしています。

- Ororo n: `UCbZogYHnnzt7JxHoO8TDvpg`
- 机上の空論: `UC7kwcBnPAI39I56s10yuQzQ`

Cyber（`UCGWb15jpJU25Gx_ckDcF0Ew`）は停止中として無効です。ほかの候補は `config.json` に無効状態で登録してありますが、実際のチャンネルIDを確認するまでは有効にしないでください。YouTubeのチャンネルページURLが `youtube.com/channel/UC...` の形式なら、その `UC...` の値がチャンネルIDです。ハンドル名や表示名からIDを推測しないでください。IDを確認できたら `id` に設定し、`enabled` を `true` にします。

## GitHub Pagesへのアップロード

1. GitHubで公開リポジトリ `MVCIinfo/mvci-live-feed` を開きます（まだ作成していない場合は公開リポジトリとして作成します）。
2. リポジトリの **Settings → Pages** を開き、**Build and deployment → Source** を **GitHub Actions** にします。
3. リポジトリのトップに `build.py`、`config.json`、`README.md`、`tests/` を追加します。フォルダーごとのアップロードで隠し `.github` が抜ける場合があるため、最初はワークフローをまだ追加しません。
4. GitHubの **Add file → Create new file** を選び、ファイル名に `.github/workflows/deploy.yml` を入力します。この配布物の同じパスにある `deploy.yml` の内容を貼り付けてコミットします。この手順で隠しフォルダーとワークフローを確実に作れます。
5. **Actions** タブで `Update and deploy MVCI feed` を開き、**Run workflow** を選びます。成功後に **Settings → Pages** に表示されるサイトURLを開きます。以降は毎時1回の更新と、`main` への変更時に自動で再取得・公開します。

ワークフローは公式の Pages Actions を使い、ビルドした `site/` を Pages artifact として公開します。シークレットやAPIキーは不要です。GitHub Actionsの実行時刻は多少前後するため、毎時更新はリアルタイム配信の保証ではありません。

## 表示内容について

ページに表示されるのはRSS内で見つかったMVCI関連タイトルの最新動画1本です。**ライブ配信中という意味ではありません。** RSSの `published` は動画の公開日時であり、配信開始時刻ではありません。RSSに該当タイトルがなければ「該当なし」と表示し、JSONの `live` は常に `null` です。一部チャンネルが取得できなくても、残りの結果で更新します。全チャンネルの取得に失敗した場合はビルドを失敗させ、GitHub Pages上の既存ページを保ちます。

タイトル判定語は `config.json` の `keywords` で変更できます（初期値: `MVCI`、`MVC:I`、`マーベルVSカプコンインフィニット`）。生成物は `site/index.html`、`site/feed.xml`（RSS 2.0、最新1件）、`site/latest.json` です。

## ローカル確認

Python 3のみで動きます。依存パッケージのインストールは不要です。

```sh
python -m unittest discover -s tests -v
python build.py
```

ビルド時は設定済みの公開RSSに接続します。テストは同梱フィクスチャを使い、ネットワークへ接続しません。
