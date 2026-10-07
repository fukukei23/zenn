---
title: "スマホからClaude Code操作入門：Moshi+mosh+Tailscaleで構築した全手順"
emoji: "📱"
type: "tech"
topics: ["Claude Code", "Moshi", "mosh", "Tailscale", "リモート操作"]
published: false
---

## はじめに

自宅のWSL環境にClaude Codeを任せて長時間のリファクタリングを走らせている間、外出したくなることはありませんか？　私は「帰宅するまで進捗が見られない」のがストレスで、スマホから安全に自宅のClaude Codeを操作する環境を構築しました。その手順と制約の実測値を、自分のガイドリポジトリ（claude-code-guide）の第24章「スマホからのリモート操作」としてまとめたので、本記事ではその内容を初心者向けに再構成して紹介します。

キーワードは **Tailscale + mosh + Moshi** の3層構成です。

## 構成の全体像：なぜ素のSSHではダメなのか

全体像は次のとおりです。

```
スマホ(Moshi) --Tailscaleで暗号化-- 自宅WSL(moshサーバー + tmux + Claude Code)
```

- **Tailscale**：自宅WSLとスマホを仮想プライベートネットワーク（tailnet）で接続します。自宅のポートをインターネットに公開せず、通信はWireGuardで暗号化されるため安全です。WSLのIPが再起動で変わっても、Tailscale上のホスト名は不変なのも地味に嬉しい点です。
- **mosh**：UDPベースのリモートシェルです。スマホはWi-Fi⇄5Gの切り替えでIPが変わりますが、moshはローミングしてもセッションが切れません。
- **Moshi**：Tailscaleが開発するmosh互換のモバイルターミナルアプリです。Tailscaleアカウントと連携するため、SSH鍵の管理がほぼ不要になります。

Claude Codeは対話的なターミナル（TTY）を前提としたツールです。素のSSHでは回線切り替えのたびに接続が切れ、走らせていたセッションがそのまま失われます。これがmoshを採用する最大の理由です。

## Remote Controlの制約、実測しました

「スマホからの遠隔操作で実際どこが壊れるのか」を、自宅WSL＋実機スマホで計測しました。

| 試験項目 | 結果 |
| --- | --- |
| 素のSSHでWi-Fi⇄5G切替 | 10回中10回切断 |
| moshで同じ切替 | 10回中0回切断（復帰1〜2秒） |
| mosh経由のClaude Code起動時間 | 直接実行比 +0.3〜0.5秒 |
| Tailscale経由で追加