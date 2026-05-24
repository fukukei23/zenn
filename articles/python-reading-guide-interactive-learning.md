---
title: "Python読解力を身につけるインタラクティブ教材を作った話"
emoji: "📖"
type: "tech"
topics: ["python", "learning", "education", "html"]
published: false
---

## はじめに

「Pythonを学びたいけれど、コードが読めない」——私自身がそうでした。

この問題を解決するため、**インタラクティブなPython読解力学習教材**を作りました。

本記事では、教材の設計思想と実装を解説します。

## 対象読者

- プログラミング初心者
- AI（ChatGPT/Claude）にコードを書かせているが、自分で読めない人
- 「コードは書けるけど読めない」という人

## 教材の特徴

### 1. 「読む」ことに特化

多くのPython教材は「書く」ことを教えます。この教材は**「読む」ことに特化**:

```html
<div class="code-block">
    <pre>
prices = [100, 200, 150, 300]
total = 0
for price in prices:
    total = total + price
print(total)
    </pre>
    <button onclick="explain()">解説を見る</button>
    <div class="explanation" style="display:none">
        <p>1行目: pricesという変数に4つの数字を入れています</p>
        <p>2行目: totalを0で初期化しています</p>
        <p>3-4行目: pricesの各要素を順番にpriceに入れて、totalに足しています</p>
        <p>5行目: totalの値を表示します → 750</p>
    </div>
</div>
```

### 2. インタラクティブ

クリックで解説が表示される仕組み:

```
[コードを見る] → [解説を見る] → [練習問題に挑戦]
```

### 3. 段階的な難易度

| レベル | 内容 |
|--------|------|
| Level 1 | 変数・代入・四則演算 |
| Level 2 | if文・for文・リスト |
| Level 3 | 関数・辞書・クラス |
| Level 4 | import・例外処理・ファイル操作 |
| Level 5 | 実践コード読解（AI生成コード） |

## 実装

### 単一HTMLファイル

依存関係ゼロの1ファイル構成:

```
python-reading-guide/
  index.html  ← 全てがこの1ファイルに
```

### GitHub Pages で公開

```bash
# gh-pages ブランチに push するだけで公開
git checkout -b gh-pages
git push origin gh-pages
```

URL: https://fukukei23.github.io/python-reading-guide/

## AI生成コードの読解

Level 5の特徴的なコンテンツ:

```
「AIが書いたこのコード、何をしているか読めますか？」

def process_data(items: list[dict]) -> dict[str, float]:
    return {
        k: sum(d[k] for d in items if k in d) / len(items)
        for k in set().union(*[d.keys() for d in items])
    }
```

→ 解説: 「辞書のリストから、各キーの平均値を計算しています」

AIに書かせたコードを読めるようになることが、**この教材の最終目標**です。

## 学んだこと

### 教材設計のコツ

1. **1行ずつ解説** — 「この行は何をしているか」を必ず書く
2. **実行結果を予想させる** — コードを見て「出力は何か」を考える
3. **段階的に難易度を上げる** — いきなりクラスは出さない

### GitHub Pagesの利点

- サーバー不要
- 無料
- `git push` だけで更新
- HTTPS対応

## まとめ

1. **「読む」に特化** したPython教材
2. **インタラクティブ** な学習体験
3. **AI生成コードの読解** が最終目標
4. **GitHub Pages** で無料公開

コードが読めないのは恥ではありません。読めるようになるための教材です。

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
