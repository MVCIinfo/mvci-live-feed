# MVCI配信フィード 保守・更新手順

資料確認日: 2026-10-11  
対象リポジトリ: [MVCIinfo/mvci-live-feed](https://github.com/MVCIinfo/mvci-live-feed)  
公開ページ: [https://mvciinfo.github.io/mvci-live-feed/](https://mvciinfo.github.io/mvci-live-feed/)  
Wikiの貼り付け先: **「配信先一覧」**  
同期先プレイリスト: [PLIA2oKVHJxPs](https://www.youtube.com/playlist?list=PLIA2oKVHJxPs)

## 先に確認すること

チャンネルと除外語は公開リポジトリの `config.json` で利用者が更新しています。この作業フォルダー内の `outputs/mvci-live-feed/config.json` は古い複製であり、現在の本番設定を示しません。将来更新するときは、必ずGitHub上の最新 `config.json` を読み、必要箇所だけ編集してください。この作業フォルダーの設定ファイルを本番に上書きしないでください。

## 設定の変更

GitHubの `config.json` を開き、`channels` の各項目を必要に応じて更新します。

| 項目 | 意味 | 注意 |
|---|---|---|
| `name` | ページや診断表示に使うチャンネル名 | 表示名を更新できます |
| `id` | YouTubeの公開チャンネルID（`UC...`） | URL等で実際のIDを確認。ハンドルから推測しない |
| `enabled` | 取得対象かどうか | 対象にするチャンネルだけ `true` |
| `keywords` | タイトルに含まれると対象にする語句 | 大文字・小文字を無視した部分文字列一致。空白は取り除かず比較 |
| `exclude_keywords` | タイトルから除外する語句 | どれか1つに一致すれば `keywords` の一致より優先して除外 |
| `title` / `site_url` | ページ名 / 公開ページURL | 通常は変更不要 |
| `playlist_id` | 同期するプレイリストID | 対象を変える場合のみ更新 |
| `max_playlist_additions_per_run` | 1回の追加上限 | 必要に応じて調整 |

除外語は `exclude_keywords` に配列で設定します。タイトルにキーワードのどれかが含まれると除外され、同時に対象語があっても除外が優先されます。比較では大文字・小文字を無視し、半角/全角スペースや改行など、すべての空白を取り除いて判定します。そのため `MVCI 闘魂部` はタイトル `mvc i 闘魂部` にも一致します。一方、`MVCI 決勝 闘魂部` はその長い語句には一致しません。闘魂部を含むタイトルも除外したい場合は、次のように `闘魂部` を追加します。

```json
"exclude_keywords": ["MVCI 闘魂部", "闘魂部"]
```

これは設定の一部だけの例です。完全な `config.json` ではありません。変更時は既存の除外語を残し、JSONのカンマや括弧を確認します。

## 取得と表示の動作

- 通常は各有効チャンネルのYouTube公開RSSを読みます。RSSが取得できずOAuthが設定済みなら、そのチャンネルのアップロード用プレイリストからYouTube APIで最近15件を取得します。これは固定日数ではなく、全履歴の検索でもありません。RSSとAPIの両方が使えない場合にのみ、そのチャンネルは失敗扱いです。
- キーワードに一致し、除外語に一致しない動画から、ページ・RSS 2.0・JSONには全チャンネルで最も新しい1本を表示します。
- YouTubeプレイリストには各有効チャンネルから最新の対象動画を1本ずつ追加候補にします。全体で最も新しい選択動画は先頭に置きます。既登録動画は重複追加せず、古い動画の削除もしません。
- 1回の追加上限は `max_playlist_additions_per_run`（通常設定は10）です。対象候補数が上限を超える場合、選択された全体最新動画を優先し、残りは後続実行に回ります。
- RSSのタイトルと状態表示、バッジは全体最新の1本だけを反映します。配信中とAPIで確認できた場合に「配信中！」、配信中でないと確認できた場合は「直近のMVCI配信」、確認不能なら「配信状態を確認できません」となります。別チャンネルの配信中動画を理由にバッジが点灯することはありません。

## Wiki「配信先一覧」の更新

既存ページのプレイヤー部分を確認して、現在のフィード用記述に差し替えます。見出しは固定文言のため自動更新されません。このURLは小文字ホスト名で現在確認できた表記です。以前、大文字ホスト表記がHTTP 404になったことがありますが、ドメイン名の大文字小文字が無効という意味ではなく、Wikiのヘルプに小文字必須の説明があるわけでもありません。

```text
#ref(https://mvciinfo.github.io/mvci-live-feed/live-status.png,nolink)
#showrss2(https://mvciinfo.github.io/mvci-live-feed/feed.xml,default,1)
#embed(https://www.youtube.com/playlist?list=PLIA2oKVHJxPs)
```

`#showrss2` の第3引数 `1` は表示件数です。第4引数（キャッシュ時間）は指定していません。Wiki上で画像の右上に出る引用符とツールチップは外部画像を示す表示で、[WikiWikiの説明](https://z.wikiwiki.jp/wikiwiki/topic/34)では非表示にする方法は案内されていません。別の「アイコンなし」指定はこの表示の設定ではありません。Wikiに画像を添付すると自動更新が止まり、フィードの最新状態を追わなくなります。

GitHub Pages側の画像は `Cache-Control: max-age=600`、Wikiの画像プロキシ側では `public, max-age=31536000`（365日）の応答が確認されています。キャッシュや配信先の挙動は変わる可能性があり、バッジの即時更新は保証されません。Cloudflareへの移行を行っても原因が解消する保証はありません。

## GitHubへの安全な反映

1. `MVCIinfo/mvci-live-feed` の最新 `main` ブランチを開きます。
2. この資料 `OPERATIONS.md` だけをリポジトリのトップに新規追加します。
3. 既存の `README.md` は全体を置換せず、`README-link.txt` の短いMarkdownリンク節だけを追記します。
4. `config.json`、コード、workflow、Secretsはこの資料の反映では変更しません。設定変更が別途必要なときは、GitHub上の現行ファイルに必要な差分だけを加えます。
5. GitHubの編集画面で **Commit changes** を実行し、`main` に反映します。
6. **Actions → Update and deploy MVCI feed** を開き、実行結果とデプロイ完了を確認します。公開ページ、RSS、JSONを開き、更新時刻と対象動画を確認します。プレイリストを編集した変更なら、プレイリストの先頭と各チャンネルの最新候補も確認します。

## Actionsの実行時刻

`.github/workflows/deploy.yml` は `main` へのpush、手動実行（`workflow_dispatch`）、およそ15分おきのスケジュールで動きます。cronは `7,22,37,52 * * * *` UTC（日本時間でも毎時7,22,37,52分頃）です。GitHub Actionsの混雑やYouTube/Wikiのキャッシュにより予定時刻から遅れることがあります。GitHubの公開リポジトリでは、60日間リポジトリに活動がないとschedule workflowが自動停止する場合があります。定期更新が止まったときはActionsのworkflowページに無効化/再有効化の案内が出ていないか確認し、必要なら **Enable workflow** で再有効化します。手動実行や閲覧だけで活動期間が延長されるとは限らないため、[GitHubのscheduleイベント仕様](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)を確認してください。

手動で更新するには、リポジトリの **Actions → Update and deploy MVCI feed → Run workflow → Run workflow** を選びます。実行後、同じworkflowのログで失敗箇所を確認し、Pagesデプロイが成功したことを確認します。

## SecretsとOAuth

必要なGitHub Actions Secret名は次の3つです。値をこの資料、README、公開Issue、Wiki、ログ、チャットに記載しないでください。

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

3つが未設定ならOAuthを使う処理（配信状態確認、RSS失敗時のAPI fallback、プレイリスト同期）は利用できません。3つのうち一部だけが設定されているとビルドは失敗します。`invalid_grant`（診断分類 `OAUTH_invalid_grant`）や `invalid_client`（診断分類 `OAUTH_invalid_client`）が出た場合は、同じOAuthクライアントから得たClient ID/Secret/Refresh Tokenの組み合わせか、対象アカウントが対象プレイリストを編集できるかを確認します。Google CloudでYouTube Data API v3が有効か、OAuth同意画面が正しく構成されているか、Testingの場合は使用アカウントがテストユーザーかも確認します。プレイリストの並べ替えには「手動」順序が必要です。

OAuth同意画面がTestingの外部アプリでは、プロフィール系以外のスコープを使うrefresh token（YouTube連携を含む）は7日で失効する場合があります。必要なら正しいGoogleアカウントで認証し直し、GitHubの該当Secretだけを更新してください。失効条件や公開ステータスは変更されるため、[GoogleのOAuth 2.0 refresh token説明](https://developers.google.com/identity/protocols/oauth2)で最新情報を確認します。資格情報やトークンをブラウザー画面や公開ログへ貼らないでください。

## よくあるエラーの切り分け

| 症状・ログ | 確認すること |
|---|---|
| `config.json` JSON parse error / trailing comma | JSONの括弧、引用符、末尾カンマを確認。例えば配列の最後の項目の後にカンマを置かない |
| 有効なチャンネルIDがない | `channels` に正しい公開チャンネルIDと `enabled: true` があるか確認 |
| RSS/APIの両方が失敗し、ログに `All channel video sources failed; previous output was preserved.` と出る | ログに出るチャンネル名・ID・RSS/APIの安全なエラー分類を確認。IDやネットワーク、OAuth、API有効化を切り分ける。全チャンネルの取得に失敗したため前回のページ出力を保持した、という意味 |
| `invalid_grant` | refresh tokenの期限切れ・失効、別OAuthクライアントのトークンとの取り違えを確認し、同一クライアントで再認証 |
| `invalid_client` | 現在のClient IDとClient Secretが同じOAuthクライアントの組み合わせか確認 |
| `accessNotConfigured` / API無効 | Google Cloudの対象プロジェクトでYouTube Data API v3を有効化 |
| `manualSortRequired` | YouTube上で対象プレイリストの並べ替えを「手動」に設定 |
| playlistNotFound / playlistItemsNotAccessible / forbidden | `PLIA2oKVHJxPs` と、認証したアカウントの閲覧・編集権限を確認 |
| `max_playlist_additions_per_run` が0以下で選択動画が未登録 | 設定値を1以上にする。登録済み動画の確認には追加上限は不要 |
| 同期後に選択動画を確認できない／先頭配置を確認できない | ActionsのAPIエラー理由、プレイリストID、動画ID、追加上限を確認。同期の読み取り確認は最大3回行う。書き込みを自動再試行しないため、原因を直してから手動再実行 |
| 成功後もWikiバッジが古い | Pagesのデプロイ、`live-status.png`、Wikiの小文字URLを確認し、キャッシュの反映を待つ。キャッシュ消去・反映時刻は保証されない |

## ファイルの役割

| ファイル/場所 | 役割 |
|---|---|
| `config.json` | ページ名、サイトURL、プレイリスト、追加上限、キーワード、除外語、チャンネル設定 |
| `build.py` | RSS/API候補の取得、フィルタ、ページ・RSS・JSON・バッジ生成 |
| `youtube_api.py` | OAuth、YouTube Data API呼び出し、プレイリスト同期 |
| `.github/workflows/deploy.yml` | 定期・push・手動実行とGitHub Pages公開 |
| `assets/` | 配信中/空状態のバッジ画像 |
| `site/` | ビルドが生成する公開用HTML、RSS 2.0、JSON、PNG |
| `tools/authorize_youtube.py` | 初回OAuth承認に使うローカル認証ツール |
| `tests/` | workflow内で実行されるフィクスチャテスト |
| `WIKIWIKI-snippet.txt` | Wiki貼り付け用コードのパッケージ内控え。ホスト表記やURLを使う前に本書の現行例とGitHub Pagesを確認 |


更新履歴: 2026-10-11 初版。公開リポジトリの現行設定を保持する更新手順、Actionsの停止条件、OAuth失効情報を記載。




