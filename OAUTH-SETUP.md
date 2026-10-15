# MVCI配信自動更新 OAuth 情報ページ

このフォルダーには、Google OAuth 同意画面から参照できるサービス概要とプライバシーポリシーの静的ページが入っています。

- ホームページ: <https://mvciinfo.github.io/mvci-live-feed/oauth/>
- プライバシーポリシー: <https://mvciinfo.github.io/mvci-live-feed/oauth/privacy.html>
- 運営者: MVCIinfo
- 連絡先: [GitHub Issues](https://github.com/MVCIinfo/mvci-live-feed/issues)

ページには現在「MVCI配信自動更新」と表示しています。Google Cloud の OAuth アプリで設定した正式なアプリ名が異なる場合は、アップロード前にページ内の表示名をその名前に合わせてください。プライバシーポリシーには「運営者確認用ドラフト」と表示しています。利用目的、OAuth 権限、保存・削除、第三者サービスの記述を運営者が確認し、実際の運用方針として採用できると判断した場合に限り、ページ本文のドラフト表示を更新してください。実際の連絡用メールアドレスを公開したい場合は、運営者が使えるアドレスを確認してからページへ追加してください。アドレスを推測してはいけません。

## 公開手順

現在のデプロイはビルド成功後に GitHub Pages へ公開する構成です。Google OAuth の `invalid_grant` でビルドが失敗している場合、ページを追加しただけでは公開されません。先に既存 OAuth クライアントを Testing の状態で再認可し、更新した `YOUTUBE_REFRESH_TOKEN` シークレットでビルドを成功させてください。Testing 中の更新トークンには期限があるため、Production へ切り替えた後にも再認可して `YOUTUBE_REFRESH_TOKEN` を更新します。

1. Google OAuth クライアントは既存のものを使います。テスト中は同じクライアントを Testing のまま再認可し、新しい refresh token で GitHub リポジトリの `YOUTUBE_REFRESH_TOKEN` シークレットを更新します。シークレット値を Issue、チャット、公開ファイルへ貼らないでください。
2. 更新後のシークレットで既存の GitHub Actions ビルドを成功させます。ビルドが通る前にページを Google の Branding に登録しても、GitHub Pages URL はまだ表示できません。
3. このアップロードパッケージの `public/oauth/index.html` と `public/oauth/privacy.html` を、同じリポジトリ相対パスに追加します。
4. パッケージに含む `.github/workflows/deploy.yml` の2行差分も適用します。既存の workflow 全体を置換せず、`python build.py` の直後にある `Copy OAuth information pages` ステップだけを追加してください。
5. GitHub Actions を実行し、公開後に2つの URL が HTTP 200 で開けること、Google ログインなしで閲覧できること、ページ内リンクが正しく移動することを確認します。公開 URL で確認するまでは、Google の OAuth Branding に登録しません。
6. Google Cloud Console の OAuth 同意画面で、ホームページとプライバシーポリシーの URL を Branding に設定します。承認済みドメインには、Google が要求する場合に限り `mvciinfo.github.io` を登録します。GitHub Pages の URL が Google に受理されることは保証できません。Google が所有権確認を要求した場合は、その画面の指示とエラーを確認してください。Search Console の URL プレフィックス確認と OAuth の承認済みドメイン設定は別の確認です。
7. OAuth アプリの Audience から Production 公開を申請・設定します。Branding の公開やスコープ検証とは別の操作です。レビューでブロックされた場合は、Google に表示された正確なエラーを記録し、その指摘に合わせて対応します。
8. Production へ切り替えた後、同じ OAuth クライアントで再認可し、新しい refresh token を `YOUTUBE_REFRESH_TOKEN` に保存して GitHub Actions を再実行します。最終ビルドと2つの公開 URL を再確認します。

OAuth の追加承認済みドメインには、Google が明示的に要求しない限り `github.io` 全体を登録しません。Pages の所有権確認用ファイルを推測して作成・公開しないでください。


