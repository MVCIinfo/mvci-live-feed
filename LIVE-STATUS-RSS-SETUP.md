# 配信中だけを表示するWiki RSSの更新

この検証版は、OAuth確認済みの全体選択動画が配信中のときだけ `live-status.xml` に1項目を出します。オフライン、状態不明、動画なしでは、通常の有効なRSSチャンネル情報を保ったまま0項目になります。Wikiの `showrss2` が0件のフィードをどう描画するかは、公開後に確認が必要です。

パッケージの `build.py` は、作成日（2026-10-12）に取得された公開リポジトリのmain版をベースに、このRSSを追加したものです。現在リポジトリにあるファイルと異なる場合は、アップロード前に差分を確認してください。

## 1. GitHubへ差分をアップロード

ZIPを展開し、`build.py` を既存リポジトリのトップにある `build.py` と置き換えます。`tests/test_live_status_feed.py` は同じパスのテストとして追加します。`WIKIWIKI-live-status-rss.txt` とこの手順書は参照用で、リポジトリへ入れなくても動作します。

既存の `config.json`、`youtube_api.py`、Actions workflowは変更しません。公開リポジトリでは、GitHubのWeb画面からファイルを置き換えてコミットできます。既存のActions設定が `python build.py` を実行してPagesへ公開する構成であることを確認してください。

## 2. GitHub Actionsで公開を確認

アップロード後、Actionsの該当workflowを手動実行し、実行が成功してPagesへ公開されたことを確認します。新URLは `https://mvciinfo.github.io/mvci-live-feed/live-status.xml` です。ブラウザーで開き、`<rss version="2.0">` と `<channel>` がある有効なXMLを確認してください。

実行が失敗した場合、Pagesには前回成功時のファイルが残ることがあります。そのため、古い「配信中！」項目が一時的に残る可能性があります。成功したActionsで新しい `live-status.xml` が公開された後にWikiを切り替えてください。

## 3. Wikiの表示行を置き換える

既存のWikiページでライブ状態バッジ画像の `#ref(...)` 行だけを、`WIKIWIKI-live-status-rss.txt` の3行に置き換えます。通常のMVCI RSS表示と `#embed` は残します。検証中はWikiのSandboxプレビューで確認し、0件時にWikiが空欄、空フィード案内などのどの表示をするかを実際に確かめてください。0件時に「配信中！」が出ないことはこのRSSの内容上保証しますが、Wikiの空表示を隠せるとは限りません。

表示内容は最新のworkflow実行結果に依存します。Actionsの実行間隔、YouTube側の状態反映、GitHub PagesとWikiのキャッシュにより遅れが出るため、即時反映は保証できません。ページ閲覧でActionsが起動することもありません。

## テスト

Python標準ライブラリだけで実行できます。XML生成、配信中1件、オフライン/不明/動画なし0件、ビルドが `site/live-status.xml` を生成することをオフラインで確認します。YouTube OAuth、ネットワーク、実アカウント、公開操作はテストしません。
