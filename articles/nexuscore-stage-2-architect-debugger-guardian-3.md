---
title: 【NexusCore Stage 2】architect/debugger/guardianで実現する3層品質保証アーキテクチャ
emoji: 🛡️
type: tech
topics: ["NexusCore", "マルチエージェント", "品質保証", "LLM駆動開発"]
published: false
---

# はじめに

LLM（大規模言語モデル）を活用したコード生成が一般的になる中で、「AIが生成したコードの品質をどう保証するか」が非常に重要なテーマになっています。AIは一発で完璧なコードを書くことは難しいため、テストが失敗したり、仕様と違う挙動をしたりすることが多々あります。

本記事では、私が開発に携わっているマルチエージェントシステム「NexusCore」のStage 2で実装された、3つのエージェント（`architect`, `debugger`, `guardian`）による協調機構「3層品質保証アーキテクチャ」について解説します。

Phase 5（テスト）とPhase 6（レビュー）の具体的な設計思想とともに、LLM駆動開発における自律的品質保証の実践方法をわかりやすく紹介します。

# 3層品質保証アーキテクチャの全体像

NexusCoreでは、LLM駆動開発における品質保証を自動化・半自動化するために、開発プロセスの中に3つの役割を持つエージェントを組み込みました。

1. **architect（設計層）**: 開発の最初段階で、要件から「設計方針」を定義し、コーディングを担当するエージェントに指示を渡します。
2. **debugger（自動修正層）**: 書かれたコードをサンドボックス環境で実行し、エラーがあれば自動的に原因を特定してコードの修正を試みます。
3. **guardian（最終判断層）**: 自動修正を終えたコードが本当に要件を満たしているかレビューし、必要に応じて人間の判断を仰ぎます。

この「設計 → 自動修正 → 人間の判断」という流れを組むことで、AIが自律的にコードを書きながらも、暴走することなく安全に開発を進めることができるようになります。

# debuggerによるサンドボックス実行と自動修正（Phase 5）

AIにコードを書かせるだけでテストを実行しないと、実行時にエラーで落ちる危険なコードが本番環境に入り込んでしまいます。

NexusCoreのPhase 5（Testingフェーズ）では、安全なサンドボックス環境を用意し、コードを実際に実行してテストを行います。もしテストが失敗した場合は、`debugger`エージェントが発火し、エラーメッセージを読み取ってコードの修正を自動で行います。

以下は、自動修正ループの概念を示したPythonのコード例です。

```python
import os

def run_testing_phase(target_files):
    # リトライの上限回数を環境変数から取得（デフォルトは3回）
    max_retries = int(os.getenv("NEXUS_DEBUG_MAX_RETRIES", 3))

    for attempt in range(max_retries):
        # サンドボックス環境でテストを実行
        test_result = run_sandbox_tests(target_files)
        
        if test_result.is_success:
            print("テスト成功！次のレビューフェーズへ進みます。")
            return "SUCCESS"
        
        # 失敗した場合はエラーを解析し、コードの修正を試みる
        print(f"テスト失敗。エラーを解析して修正を試みます ({attempt + 1}/{max_retries})")
        error_log = test_result.get_error_log()
        fix_code_with_debugger(error_log, target_files)
    
    # リトライ上限に達しても直らない場合はエラーを返す
    return "FAILED"

# 実行例
if __name__ == "__main__":
    files_to_test = ["/path/to/target_file.py"]
    result = run_testing_phase(files_to_test)
    if result == "FAILED":
        raise Exception("自動修正の上限に達しました。人間の確認が必要です。")
```

この仕組みの重要なポイントは、無限ループに陥らないように`NEXUS_DEBUG_MAX_RETRIES`のような環境変数でリトライ回数の上限を設けている点です。AIが同じ間違いを繰り返した際に、システムが永遠に止まらなくなってしまうのを防いでいます。

# guardianによる人間を介在させた終端状態（Phase 6）

自動テストをパスしたコードであっても、「仕様を正しく満たしているか」「セキュリティ上の問題がないか」といった側面は、AIだけでは完全に保証できません。

そこでPhase 6（Reviewフェーズ）では、`guardian`エージェントが最終的なレビューを行います。ここでの最大の特徴は、単純な「成功・失敗」という2択ではなく、**3値の終端状態**を定義していることです。

1. **APPROVED**: コードが要件を満たしており、自動で次のプロセス（マージやデプロイなど）に進んで良い状態。
2. **NEEDS_HUMAN_REVIEW**: 自動テストは通ったものの、設計の複雑さや潜在的なリスクがあり、人間の目による最終確認が必要な状態。
3. **REJECTED**: 明らかな仕様違反やエラーがあり、作り直しが必要な状態。

この終端状態をシステム（CLIなど）の終了コードに反映させることで、CI/CDパイプラインなどで「自動マージ」か「人間によるレビュー待ち」かをシステム的にハンドリングできるようになります。

```python
def determine_terminal_state(review_result):
    if review_result.has_critical_issues:
        return "REJECTED"
    elif review_result.has_minor_risks or review_result.is_complex_logic:
        return "NEEDS_HUMAN_REVIEW"
    else:
        return "APPROVED"

# レビュー結果に基づく終了コードのハンドリング例
terminal_state = determine_terminal_state(latest_review)

if terminal_state == "APPROVED":
    exit(0) # 正常終了
elif terminal_state == "NEEDS_HUMAN_REVIEW":
    print("注意: 人間によるレビューが必要です。")
    exit(2) # 特定の終了コードで人間への通知をトリガー
else:
    exit(1) # エラー終了
```

`NEEDS_HUMAN_REVIEW`という状態を設けることで、「AIに任せきりにする危険性」を減らしつつ、人間は「本当に必要なレビュー」だけに集中できるようになります。

# おわりに

NexusCoreのStage 2で実装した品質ループにより、`architect`が示した方針に基づいて`debugger`がコードを磨き上げ、最後に`guardian`が人間の判断を仰ぐための判断材料を提供する、堅牢なパイプラインが完成しました。

LLM駆動開発を進める上で、AIの自動化をどこまで信頼し、どこで人間が介入するか（Human-in-the-Loop）を設計することは非常に重要です。単純な作業はAIに任せ、複雑な判断や最終的な承認は人間が行うというバランスを取ることで、開発のスピードと安全性を両立させることができます。

これからマルチエージェントシステムの構築や、LLMを使った開発プロセスの自動化を検討している方の参考になれば幸いです。