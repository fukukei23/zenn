---
title: "CI/CD超入門 — コードを書くだけで自動テスト・自動デプロイ"
emoji: "🔄"
type: "tech"
topics: ["cicd", "githubactions", "devops", "programming"]
published: true
---

## CI/CDとは？

CI/CDは「コードをpushしたら自動でテスト・Lint・ デプロイを実行する」仕組みです。

### CI — 継続的インテグレーション（Continuous Integration）

```
コードを書く → push → 【自動】テスト実行 → 【自動】Lint → 結果通知
```

### CD — 継続的デプロイ（Continuous Deployment）

```
CIが通る → 【自動】ステージング/本番にデプロイ
```

## なぜCI/CDするのか？

| 好处 | 説明 |
|---|---|
| **バグの早期発見** | pushのたびにテストが実行される |
| **手動作業の削減** | テスト、デプロイを自動化了 |
| **安全なリファクタリング** | 変更してもCIが通れば安心 |

## GitHub ActionsでCIを設定

GitHub ActionsはGitHub免费提供的CI/CD服務です。

### Pythonの例

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest ruff mypy

      - name: Lint
        run: ruff check .

      - name: Type check
        run: mypy src/ --ignore-missing-imports

      - name: Test
        run: pytest tests/ -v
```

### TypeScriptの例

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [20, 22]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js ${{ matrix.node-version }}
        uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
          cache: "npm"

      - name: Install dependencies
        run: npm ci

      - name: Lint
        run: npx biome check src/

      - name: Type check
        run: npx tsc --noEmit

      - name: Test
        run: npx vitest run
```

## タグpushで自動publish（CD）

npmパッケージを自動publishする例：

```yaml
# .github/workflows/publish.yml
name: Publish

on:
  push:
    tags: ["v*"]  # v1.0.0 のようなタグをpushで発動

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          registry-url: "https://registry.npmjs.org"
      - run: npm ci
      - run: npm test
      - run: npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

## Trunk-Based Development

CI/CDを効果を出すためには、**Trunk-Based Development**（メインラインベースの開発）も大切です。

| 原则 | 内容 |
|---|---|
| mainは常にデプロイ可能 | 壊れたコードはmainにマージしない |
| 短命なブランチ | 長く放置するブランチ作らない |
| 個人開発ならmain直push | featureブランチ不要 |

## まとめ

| 項目 | 内容 |
|---|---|
| **CI** | push時に自動でテスト・Lintを実行 |
| **CD** | CIが通ったら自動でデプロイ |
| **設定ファイル** | `.github/workflows/ci.yml` |
| **Trunk-Based** | mainは常にデプロイ可能状態を保つ |

CI/CDを導入すれば、「コードを書いてpushすれば勝手にテストされて、勝手にdeployされる」世界が待っています。
