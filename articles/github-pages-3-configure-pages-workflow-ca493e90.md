---
title: GitHub Pages自動デプロイ設定の3つの落とし穴：configure-pagesとworkflow重複を防ぐには
emoji: 🚧
type: tech
topics:
  - GitHub
  - CI
  - GitHubPages
  - 初心者向け
published: false
---

## はじめに

静的な学習用サイト（模擬試験ガイド）をGitHub Pagesで自動公開しようとしたところ、1晩で3つの落とし穴を連続で踏みました。

1. **Pages未有効化エラー**：リポジトリでPagesが有効化されていないのにデプロイした
2. **二重デプロイ**：公式テンプレートworkflowと自作workflowが両方走った
3. **workflow競合**：static.yml / deploy.yml の2本が同じ役割を持ってしまった

「公式ドキュメント通りにworkflowを置いたのに失敗する」「ログは緑なのに公開内容がおかしい」という状態になりがちで、初心者ほど原因の切り分けに悩むポイントです