# GitHub アップロード差分ガイド

このフォルダーには `MVCIinfo/mvci-live-feed` に適用する差分だけを収録しています。Python ビルド、ライブ状態 RSS、OAuth 情報ページ、Cloudflare Worker の配置と手順が含まれます。

## 追加・更新するファイル

- `build.py` — 最新動画のライブ状態に応じて項目を出す `live-status.xml` を生成
- `tests/test_live_status_feed.py` — ライブ中、オフライン、不明、動画なし、およびビルド出力のテスト
- `WIKIWIKI-live-status-rss.txt`、`LIVE-STATUS-RSS-SETUP.md` — Wiki 表示用 snippet と切替手順
- `public/oauth/index.html`、`public/oauth/privacy.html` — Google OAuth の情報ページ。表示名は「MVCI配信自動更新」
- `OAUTH-SETUP.md` — OAuth 情報ページと公開手順
- `.github/workflows/deploy.yml` — 既存 workflow の Pages artifact 作成前に `public/` を `site/` へコピーする2行の追加
- `cloudflare/` — Actions 起動 Worker、Node テスト、導入手順

GitHub リポジトリのルートへこのフォルダーの中身をアップロードし、同じ相対パスへ配置してください。`config.json`、`youtube_api.py`、`README.md`、`OPERATIONS.md` は含めていません。既存の値・運用手順をそのまま使います。旧 ZIP、キャッシュ、画像中継版も含めていません。

`build.py` と Python テストはローカル基準アプリの一時コピー上で確認します。Cloudflare Worker は `cloudflare/` で `npm test` を実行します。

## 現在の保留事項

GitHub Actions の OAuth 更新で `invalid_grant` が発生しているため、新しいページや RSS はまだ GitHub Pages に公開されていません。既存 OAuth クライアントで再認可して `YOUTUBE_REFRESH_TOKEN` を更新し、ビルドを成功させてください。トークンは公開ファイルやチャットに貼らないでください。OAuth の Branding 登録と Wiki の RSS 切替は、Pages 上のページと RSS を確認してから行います。

プライバシーポリシーには「運営者確認用ドラフト」の表示を残しています。運営者が記載内容を確認し、実際の運用方針として採用すると判断した場合にのみ、ページ本文のドラフト表示を更新してください。

OAuth の再認可と `invalid_grant` 解消、GitHub Actions の成功、Pages の表示確認、Google Branding の審査・設定は未完了です。Cloudflare Worker の作成、KV binding、Secret 設定、GitHub fine-grained token 作成と登録、Cron/WebSub 設定、Worker 公開も未完了です。具体的な設定値は `OAUTH-SETUP.md` と `cloudflare/SETUP.md` を参照してください。
