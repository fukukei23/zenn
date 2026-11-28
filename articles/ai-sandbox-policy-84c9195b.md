---
title: "AI生成コードを安全化するsandbox_policy設計：事前検査・資源制限・禁止パスの実践"
emoji: "🔐"
type: "tech"
topics: ["python", "security", "testing"]
published: false
---

# はじめに

LLMが生成したPythonコードをそのまま実行するのは危険です。無限ループでCPUとメモリを食いつぶしたり、`os` や `subprocess` で機密ファイルを読み取ったり、外部へ通信したりするコードが生成される可能性は常にあります。

自分のリポジトリ（NexusCore）では、AI生成コードを隔離実行するためのsandboxを最近仕上げました。開発の流れは次の4段階です。

1. 散在していたポリシー値を「設定値」として一つのデータクラスに整理
2. 実行関数に事前検査を接続（fail-closed）
3. 自己検査テストを11件追加（coverage 91.18% → 94.49%）
4. 5台のAIレビューアにレビューを依頼し、29件の指摘から6件の修正を採用

この記事では、その中で学んだ「sandbox_policyの設計ポイント」をPythonコードとともに初心者向けに解説します。

# policyをひとつのデータクラスに整理する

最初の課題は、制限値がコードのあちこちにマジックナンバーとして散らばっていたことでした。まずは「メモリ上限・CPU時間上限・禁止モジュール・禁止パス」を1つのdataclassにまとめます。

```python
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class SandboxPolicy:
    memory_limit_mb: int = 512
    cpu_time_seconds: int = 10
    forbidden_modules: frozenset = frozenset(
        {"os", "subprocess", "socket", "shutil"}
    )
    forbidden_paths: tuple = ("/etc", "/root", "/path/to/.env")
```

`frozen=True` は「作成後に書き換え不可」、`frozenset` は「重複なし・変更不可の集合」です。frozen=True` と `frozenset` の不変性によって、設定が誤って上書きされる事故を防げます。

次に、このpolicyをYAMLから読み込めるようにします。ここで大事なのが **YAML破損時のfallback** です。

```python
import yaml

def load_policy(path: str) -> SandboxPolicy:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        # 読めなければ安全な既定値にフォールバック（fail-safe）
        return SandboxPolicy()
    default = SandboxPolicy()
    # 禁止モジュールは「和集合」: 設定側で緩めることはできない
    return SandboxPolicy(
        memory_limit_mb=data.get("memory_limit_mb", default.memory_limit_mb),
        cpu_time_seconds=data.get("cpu_time_seconds", default.cpu_time_seconds),
        forbidden_modules=default.forbidden_modules
        | frozenset(data.get("forbidden_modules", [])),
        forbidden_paths=tuple(data.get("forbidden_paths", ())),
    )
```

レビューで指摘された典型的なバグが2つ、この短いコードに隠れています。

- **例外捕捉漏れ**：当初は `yaml.scanner.ScannerError` だけを捕まえていましたが、これは `yaml.YAMLError` のサブクラスです。親クラスの `YAMLError` を捕捉する方が安全で簡潔です。
- **禁止リストの上書きバグ**：当初は設定の `forbidden_modules` がデフォルトを**置き換えて**いました。これでは空リストを書くだけで禁止が全部解除されます。「設定で追加はできても解除はできない」という要件を満たすように、設定側では禁止モジュールを追加できる一方、既定の禁止モジュールは解除できないよう、和集合（`|`）でマージするようにしました。

# 実行前の事前検査と絶対パス正規化

policyを決めただけでは意味がありません。実行関数 `run_in_sandbox` の**冒頭で検査し、通らなければ即return**する「fail-closed（怪しいときは閉じる）」構造にします。fail-open（とりあえず続行）はセキュリティの基本に反します。

```python
def run_in_sandbox(code: str, policy: SandboxPolicy) -> RunResult:
    # ① 事前検査: import文の静的チェック（拒否なら実行しない）
    for module in extract_imports(code):
        if module in policy.forbidden_modules:
            return RunResult(status="rejected",
                             reason=f"forbidden module: {module}")
    # ② メモリ・CPU制限を引数として渡し、制限付きで実行
    return _execute(code, mem_mb=policy.memory_limit_mb,
                    cpu_sec=policy.cpu_time_seconds)
```

もう一つ、レビューで拾われたのが **絶対パス正規化** です。禁止パスの判定を文字列の `startswith` だけで行うと、`/path/to/data/../../.env` のような相対パス混じりのトラバーサルをすり抜けられます。判定前に `os.path.abspath` で正規化しましょう。

```python
def is_forbidden_path(target: str, forbidden_paths: tuple[str, ...]) -> bool:
    normalized = os.path.abspath(target)  # まず絶対パスへ正規化
    for forbidden in forbidden_paths:
        base = os.path.abspath(forbidden)
        if normalized == base or normalized.startswith(base + os.sep):
            return True
    return False
```

`base + os.sep` と区切り文字を明示するのは誤検知対策です。`"/etc"` を `startswith` で判定すると `/etc2` という無関係なパスまで拒否してしまいます。

# 自己検査テストを書いて、AIレビューで仕上げる

ポリシーコードは「守りの要」なので、自分でテストを書いて枯れているかを確認しました。YAML破損・timeout即return・リトライ継続・打ち切りなどのケースを11件追加し、coverageは91.18%から94.49%まで上がりました。

```python
import pytest

def test_broken_yaml_falls_back_to_default(tmp_path):
    broken = tmp_path / "policy.yaml"
    broken.write_text(":::: not [ valid yaml", encoding="utf-8")

    policy = load_policy(str(broken))

    assert policy.memory_limit_mb == 512  # 破損時も既定値に戻る

def test_forbidden_path_detects_traversal():
    assert is_forbidden_path(
        "/path/to/data/../../.env", ("/path/to/.env",)
    ) is True

@pytest.mark.parametrize("module", ["os", "subprocess", "socket"])
def test_forbidden_modules_cannot_be_relaxed(module):
    relaxed = load_policy_from_dict({"forbidden_modules": []})
    assert module in relaxed.forbidden_modules  # 空設定でも緩めない
```

`tmp_path` はpytest組み込みのフィクスチャで、テストごとに独立した一時ディレクトリを作ってくれます。ファイル破損テストを安全に書けるので積極的に使いましょう。

最後に、5台のAIレビューアにこの変更をレビューしてもらい、29件の指摘から6件を採用しました。採用したのは前述の例外捕捉・和集合化・abspath正規化に加え、**デフォルト値が2箇所に重複定義されてズレていた問題の一元化**、テストの重複削除、そして「実は接続されていない引数」の明記です。特に重複デフォルト値と未接続引数は、AIレビューが得意とする「全コードを横断して突き合わせる」系のミスで、人間の目では見落としやすい部類です。

# おわりに

今回の設計で効いた原則を3つにまとめます。

- **fail-closed**：検査に通らないなら実行しない。エラー時も「止める」方向に倒す
- **緩められない構造**：禁止リストは和集合でマージし、設定側で弱体化できない
- **自己検査**：守りのコードこそ、破損入力・トラバーサル・緩和試行をpytestで固める

sandboxの完成形はこれで終わりではありませんが、「policyの実値整理 → 事前検査の接続 → テスト追加 → 複数レビュー」という順序で段階的に固めたこの進め方は、セキュリティまわりの実装一般に使える型だと思います。AI生成コードを扱う方は、ぜひ参考にしてみてください。