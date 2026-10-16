# Cloudflare Worker + KV の導入

この Worker は YouTube の公開 WebSub 通知をすぐ処理し、5分ごとに公開 RSS と YouTube Data API v3 で対象動画の開始・終了状態を確認して、変化があった時だけ GitHub Actions を起動します。初回 Cron は現在状態の基準スナップショットを保存して dispatch します。Cloudflare に Google OAuth 認証情報は置きません。

## Worker と KV

1. Cloudflare の **Workers & Pages** で `mvci-feed-trigger` Worker を作成し、このフォルダーの `worker.js` を配置してデプロイします。
2. **Storage & databases → KV** で `mvci-feed-trigger-state` namespace を作成します。
3. Worker の **Settings → Bindings** で Workers KV binding を追加し、Variable name を `STATE` にして namespace を結び付けます。
4. **Settings → Triggers → Cron Triggers** に `*/5 * * * *` を登録します。

### Wrangler CLI で既存 Worker を更新

Node.js 22 以降と npm を用意し、このリポジトリを取得して `cloudflare` フォルダーを作業ディレクトリにし、バージョン固定の公式 Wrangler CLI を `npx` で実行します。設定ファイルは既存 Worker の `STATE` namespace を参照するだけで、KV namespace は作成しません。`keep_vars: true` は既存の dashboard variables を保ち、通常の Worker deploy は既存の Secret bindings を削除しません。`observability` 設定も invocation logs、永続化、サンプリング率を明示して既存値を保ちます。

```sh
npx wrangler@4.151.1 login --device --browser=false --scopes account:read workers_scripts:write
npx wrangler@4.151.1 --config wrangler.jsonc deploy
```

localhost callback が接続拒否になる場合やログインが2分程度でタイムアウトする場合は、device login を使います。CLI が表示した URL をそのまま Edge で開き、ユーザー本人が **Continue** と **Authorize** を選びます。CLI 側で認可完了を確認してから deploy を実行してください。認証コードやトークンを共有したり、Worker のソースや設定ファイルに保存したりしないでください。

## Variables と Secrets

**Settings → Variables and Secrets** に以下を設定します。Worker 独自の JSON ログと `/health` response は Secret 値を返しません。Cloudflare の platform request logs は callback URL path を記録することがあるため、ログのアクセス権と保持期間も確認してください。

| 名前 | 種類 | 値 |
|---|---|---|
| `WORKER_URL` | Text | Worker の `https://<name>.<account>.workers.dev` origin（末尾スラッシュなし） |
| `GITHUB_TOKEN` | Secret | `MVCIinfo/mvci-live-feed` だけに許可した fine-grained PAT。Actions: Read and write |
| `HUB_SECRET` | Secret | WebSub 署名検証用の別個の暗号学的乱数、64桁16進文字列 |
| `WEBHOOK_TOKEN` | Secret | コールバックURL用の別個の暗号学的乱数、64桁16進文字列 |
| `YOUTUBE_API_KEY` | Secret | YouTube Data API v3 の公開データ読み取り用 API key。OAuth client/refresh token ではありません |

Google Cloud で YouTube Data API v3 を有効にし、API key を作成します。API restrictions で **Restrict key → YouTube Data API v3** を必ず選択してください。キーは `x-goog-api-key` ヘッダーで送信し、URL、ログ、health response に含めません。OAuth 認証情報は Cloudflare に設定しません。

`HUB_SECRET` と `WEBHOOK_TOKEN` は PowerShell で個別に作れます。2回実行し、それぞれの出力を使います。

```powershell
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
-join ($bytes | ForEach-Object { $_.ToString('x2') })
```

## 動作と負荷

公開 `config.json` の有効なチャンネル（最大40件）ごとに RSS を読み、`keywords` に一致し `exclude_keywords` に一致しないタイトルだけを候補にします。除外語は NFKC 正規化、空白除去、大小文字を無視して判定し、包含語より優先します。成功したRSSチャンネルの最新候補と、過去の live/upcoming 候補を照合し、RSS失敗チャンネルの既知候補もAPI照合のため保持します。追跡総数は最大120件です。開始・終了を追跡します。1回の Cron は config 1回、RSS 最大40回、YouTube API 最大3回、WebSub購読要求最大4回、変化時の GitHub dispatch 最大1回で、最大49 subrequest です。

YouTube Data API の `videos.list` は最大50 IDずつ照合します。上限まで使う場合、最大3 calls/5分、864 quota units/日（1 call = 1 unit）です。これはこの Worker の利用分だけの見積もりです。同じ Google Cloud project を使う GitHub Actions の playlist 取得なども、同じ project の日次 quota を消費します。Cloudflare Workers Free は1日100,000 Worker requests、1 invocation あたり50 subrequestsです。外部HTTP subrequests は最大49/cronです。Workers KV Free の上限は1日100,000 reads、1,000 writesです。monitor snapshot と health の2キーを毎回更新するため576 KV writes/日を使い、pending・lease・通知記録など他の KV writes に残るのは最大424/日です。KV reads は40チャンネル時に Cron だけで最大約23,328/日（1 snapshot read + 最大80 subscription readsを288回）で、通知や verification の読み取り分は別途加算されます。Free 上限を超えると該当する KV 操作は失敗します。最新条件は[Workers limits](https://developers.cloudflare.com/workers/platform/limits/)と[KV limits](https://developers.cloudflare.com/kv/platform/limits/)で確認してください。

`/health` は `ready`、不足している設定名、最後の monitor 時刻/status/追跡件数を返します。Secret 値と callback path は返しません。独自ログは `scheduled_run_complete`、`monitor_dispatch_ok`（baseline/change）、status を記録します。初回基準作成時も1回 dispatch されます。失敗時は以前の monitor snapshot を維持し、次の Cron で再試行します。異常な RSS/API 応答を終了扱いにはしません。

RSS が古い動画を返さない場合や、短い配信、YouTube の遅延・欠落がある場合は状態変化を捕捉できないことがあります。WebSub も開始・終了の到達を保証しません。GitHub workflow の既存 `schedule:` は Cloudflare Cron と dispatch の稼働を確認してから削除してください。`workflow_dispatch:` やその他の trigger は残します。

## 既存 WebSub の確認

既存の公開 WebSub 通知では、YouTube の challenge を検証し、HMAC 署名が有効な通知だけを即時 dispatch します。`/health` が `ready: true` になること、GitHub Actions に `deploy.yml` の `workflow_dispatch` が現れること、Cron logs に `scheduled_run_complete` が記録されることを確認します。テスト用の偽通知 endpoint はありません。

公式資料: [YouTube Data API quota costs](https://developers.google.com/youtube/data/determine_quota_cost) · [YouTube Push Notifications](https://developers.google.com/youtube/v3/guides/push_notifications) · [YouTube Data API videos.list](https://developers.google.com/youtube/v3/docs/videos/list) · [Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/) · [Cloudflare KV](https://developers.cloudflare.com/kv/get-started/) · [Cloudflare KV limits](https://developers.cloudflare.com/kv/platform/limits/) · [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/) · [GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
