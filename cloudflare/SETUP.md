# Cloudflare Workers + KV 導入ガイド

このパッケージは、YouTube の公開 WebSub 通知を受けて GitHub Actions の `workflow_dispatch` を起動し、さらに15分ごとの定期起動も行う Cloudflare Worker です。YouTube の OAuth 認証情報は扱いません。OAuth とチャンネル同期は引き続き GitHub 側の workflow が担当します。

## 1. Cloudflare アカウントを作る

1. [Cloudflare のサインアップ](https://dash.cloudflare.com/sign-up)を開き、メールアドレスとパスワードでアカウントを作成します。
2. Cloudflare から届く確認メールを開き、メールアドレスを確認します。
3. ダッシュボードで **Workers & Pages → Create application** を開き、表示されるスターターまたはテンプレート（Hello World が表示される場合はそれ）から Worker を作成します。`mvci-feed-trigger` という名前で作成してデプロイします。GitHub リポジトリの接続やインポートは選びません。
4. Worker のコード画面で既存コードをすべて置き換え、同梱の `worker.js` 全文を貼り付けて **Deploy** します。

Workers Free の範囲で始められます。独自ドメインの購入、DNS の移行、支払い情報の登録は不要です。Cloudflare が割り当てる `*.workers.dev` URL を使います。Free プランの上限・条件は変更されることがあるため、[Workers の料金ページ](https://developers.cloudflare.com/workers/platform/pricing/)も参照してください。

## 2. KV を作って Worker に結び付ける

1. Cloudflare ダッシュボードの **Storage & databases → KV** を開き、`mvci-feed-trigger-state` という namespace を作成します。
2. Worker の **Settings → Bindings**（または **Bindings**）で **Add binding → Workers KV** を選びます。
3. Variable name を `STATE` にして、先ほどの `mvci-feed-trigger-state` namespace を選択し、保存・デプロイします。

この KV には検証済み WebSub リースと通知の120秒抑制記録を保存します。GitHub の定期ビルドはこの抑制記録の影響を受けません。

## 3. Secret と URL を登録する

Worker の **Settings → Variables and Secrets** で次の4つを登録します。`GITHUB_TOKEN`、`HUB_SECRET`、`WEBHOOK_TOKEN` は **Secret**、`WORKER_URL` は **Text** として登録します。

| 名前 | 種類 | 入れる値 |
|---|---|---|
| `WORKER_URL` | Text | Worker の `workers.dev` URL の origin。例: `https://mvci-feed-trigger.<アカウント識別子>.workers.dev`。末尾の `/`、パス、クエリは付けません。|
| `GITHUB_TOKEN` | Secret | 手順4で作る GitHub fine-grained PAT |
| `HUB_SECRET` | Secret | 暗号学的乱数で作った64桁の16進文字列 |
| `WEBHOOK_TOKEN` | Secret | 別の暗号学的乱数で作った64桁の16進文字列 |

PowerShell で2つの異なる乱数値を作る例です。各コマンドの出力をそれぞれ対応する Cloudflare Secret に貼り付けます。これらの値は GitHub や公開ファイルに置かず、チャットにも貼らないでください。

```powershell
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
-join ($bytes | ForEach-Object { $_.ToString('x2') })
```

もう一度実行して、もう一方のSecret用の値を作ります。値の控えはパスワード管理ツールなどに保管してください。Secret を更新した場合は Worker を再デプロイします。

## 4. GitHub の最小権限トークンを作る

1. GitHub の **Settings → Developer settings → Personal access tokens → Fine-grained tokens** でトークンを生成します。
2. Resource owner に `MVCIinfo` を選び、Repository access は `Only select repositories` にして `mvci-live-feed` だけを選びます。
3. Repository permissions の **Actions** を **Read and write** にします。**Metadata: Read-only** は自動で含まれます。
4. 期限は運用上管理できる期間（例: 90日）に設定し、期限前に更新する予定を記録します。組織の承認が必要な場合は、承認後に使います。
5. 生成直後に表示される値を Cloudflare の `GITHUB_TOKEN` Secret に登録します。トークンをリポジトリのファイル、Actions のログ、公開チャットに書きません。

この Worker は固定された `MVCIinfo/mvci-live-feed` の `deploy.yml` に `main` を指定して dispatch します。`GITHUB_TOKEN` は workflow YAML や設定 JSON から読みません。

## 5. Cron Trigger を設定する

Worker の **Settings → Triggers → Cron Triggers** で、次の式を登録します。

```text
7,22,37,52 * * * *
```

これは15分ごとの実行です。Cron の初回反映に最大15分程度かかることがあります。新規 Worker では Cron Events の画面に実行履歴が表示されるまで最大30分程度かかる場合があります。GitHub Actions 側の `workflow_dispatch` を見ると、Cron ログ表示を待たずにdispatchを確認できます。Cron イベントは登録した UTC 時刻で動きます。[Cron Triggers の公式説明](https://developers.cloudflare.com/workers/configuration/cron-triggers/)を参照してください。

各 Cron 実行では、まず GitHub dispatch を1回試し、その後 WebSub の新規購読・期限が近い購読の更新を試します。購読処理が失敗してもdispatchは試行されます。YouTube の確認GETに対して初めて応答した時点でリースを検証済みとして記録します。購読リクエストの受付応答 `202` または `204` だけでは検証完了と見なしません。

## 6. 動作を確認する

1. `https://mvci-feed-trigger.account-id.workers.dev/health` を開きます。`account-id` はCloudflareが割り当てた実際のURLの値に置き換えてください。`ready: true` は必須設定が存在し形式を満たすことを示しますが、GitHub token の有効性は示しません。不足設定の場合は変数名だけが返り、Secret の値は表示されません。
2. GitHub の `MVCIinfo/mvci-live-feed` の Actions で `deploy.yml` が **workflow_dispatch** イベントとして実行されることを確認します。成功すれば `GITHUB_TOKEN` の有効性と権限も確認できます。
3. Worker の **Logs** を開き、Cron 実行後に `scheduled_dispatch_ok` と `subscription_requested` が記録されることを確認します。続けて YouTube から確認GETを受けると `subscription_verified` が記録されます。`subscription_requested` だけでは購読検証済みではありません。このWorkerが出力する独自ログにはコールバックURLやトークンを含めません。
4. 実際の通知は、新しい動画など YouTube が対象フィード通知を発行した時に検証されます。偽の通知を送るためのテスト用エンドポイントはありません。

通知の抑制記録には KV の eventual consistency があるため、同時到着した通知を厳密に一度だけ処理する保証はありません。既存のビルド同期処理の重複排除を利用してください。YouTube から Cloudflare への新着通知だけでは、開始・終了状態を必ず捕捉できるとは限りません。短いライブ配信や通知の遅延、欠落に備え、15分Cronを併用します。Cron も完全な即時性や無停止を保証しません。

## 7. GitHub のスケジュールを整理する

Cloudflare Cron と `workflow_dispatch` の両方が正常に動くのを確認してから、`MVCIinfo/mvci-live-feed` の `.github/workflows/deploy.yml` で、既存の `schedule:` にある **schedule トリガーだけ**を削除します。`workflow_dispatch:`、`push:`、ジョブ、その他の設定は残します。Cloudflare の設定前に GitHub 側のスケジュールを消さないでください。

workflow の `on:` 部分は、現在の設定を保ったまま例えば次の形にします（既存の push 条件はそのまま移します）。

```yaml
on:
  workflow_dispatch:
  push:
    branches:
      - main
```

GitHub は長期間リポジトリに活動がない場合、スケジュール workflow を自動停止することがあります。Cloudflare からの dispatch はスケジュール起動ではありません。workflow 自体が停止・無効化されている場合は、GitHub Actions 画面で有効にしてください。

## 8. リースと運用

Worker は現在の公開 `config.json` にある `enabled: true` の有効な `UC` チャンネルIDを読みます。ID は重複を除き最大40件です。設定への追加は次回 Cron で購読要求されます。削除済みIDは通知時に拒否されますが、ハブ側の購読は期限切れまで残る場合があります。

`HUB_SECRET` は WebSub の HMAC 署名検証に使用し、`WEBHOOK_TOKEN` はコールバックパスを推測されにくくします。どちらも別々のランダム64桁16進値を保管し、漏えい時は値をローテーションしてください。トークンの期限切れや権限変更後は `GITHUB_TOKEN` を交換します。

WebSub の署名は、ハブの通知本文が改ざんされていないことを確認する仕組みです。[YouTube の Push Notifications ガイド](https://developers.google.com/youtube/v3/guides/push_notifications)と[WebSub仕様](https://www.w3.org/TR/websub/)に沿い、ハブの確認要求には challenge を返し、イベントPOSTは HMAC 検証後に処理します。

このパッケージは既存のサイト画像キャッシュや表示不具合を直しません。ライブ表示側の RSS や画像キャッシュ問題は別の修正が必要です。この Worker に YouTube OAuth を移すこともありません。

## 公式資料

- [Cloudflare アカウント作成](https://developers.cloudflare.com/fundamentals/account/create-account/)
- [Dashboard から Worker を作成](https://developers.cloudflare.com/workers/get-started/dashboard/)
- [Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
- [Secrets の設定](https://developers.cloudflare.com/workers/configuration/secrets/)
- [KV の開始ガイド](https://developers.cloudflare.com/kv/get-started/)
- [Workers の料金](https://developers.cloudflare.com/workers/platform/pricing/)
- [GitHub workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
- [GitHub fine-grained PAT の作成](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
