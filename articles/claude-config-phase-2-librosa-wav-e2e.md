---
title: "【claude-config Phase 2】librosaで実測オーディオ解析：wav生成テストフィクスチャでE2Eテストを実現"
emoji: "📝"
type: "tech"
topics: ["Python", "librosa", "オーディオ解析", "E2Eテスト", "Claude Code"]
published: false
---

title: "【claude-config Phase 2】librosaで実測オーディオ解析：wav生成テストフィクスチャでE2Eテストを実現"
emoji: "🎵"
type: "tech"
topics: ["Python", "librosa", "オーディオ解析", "E2Eテスト", "Claude Code"]
published: false
---

## はじめに

Claude Codeの振る舞いをカスタマイズする設定ファイル群を管理する「claude-config」プロジェクトでは、Phase 2としてオーディオ解析機能の実装を進めました。

オーディオ処理のテストにおいて最大の壁となるのが「テストデータの用意」です。実際の楽曲ファイルは著作権の問題があり気軽にリポジトリにコミットできず、かといってランダムノイズでは特定の周波数帯域やテンポを持つ楽曲の再現ができません。

本記事では、librosaを用いたオーディオ解析テストの実践手法として、意図的な特性を持つwavファイルを自動生成するアプローチと、実測データと文字列情報を組み合わせた「融合評価関数」の設計について解説します。

## テストフィクスチャとしてのwav自動生成

E2E（エンドツーエンド）テストを安定して実行するためには、常に同じ特性を持つテストデータが必要です。今回のプロジェクトでは、以下の4種類のテストパターンを想定し、それぞれに対応するwavファイルをPythonのスクリプトで生成するテストフィクスチャを作成しました。

- **v2低音**: 特定の低周波数帯域を強調したデータ
- **祭礼前夜**: 複雑な波形や特定のテンポを持つデータ
- **monotone**: 単一の周波数を持つデータ
- **melodic**: 複数の周波数が遷移するデータ

これらを生成することで、実データに依存せずにオーディオ解析ロジックの正確性を検証できます。以下は、numpyとsoundfileを用いて単音および低音のwavファイルを生成する例です。

```python
import numpy as np
import soundfile as sf

def generate_test_wav(output_path, freq, duration=2.0, sr=22050):
    """
    指定した周波数のサイン波を生成し、wavファイルとして保存する
    """
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # 振幅を0.5に抑えてクリッピングを防ぐ
    waveform = 0.5 * np.sin(2 * np.pi * freq * t)
    sf.write(output_path, waveform, sr)

# 各フィクスチャの生成例
# 単音（A4 = 440Hz）
generate_test_wav('/path/to/fixtures/monotone.wav', freq=440)

# 低音（C2 = 65.4Hz）
generate_test_wav('/path/to/fixtures/low_freq.wav', freq=65)
```

このように生成スクリプトをコード化しておくことで、テスト実行時に必要なフィクスチャをいつでも再現可能です。また、テスト環境に依存しない汎用的なパス（`/path/to/...`）を用いることで、異なるPC環境に移行してもスクリプトがそのまま動くようになります。

## librosaによる実測解析と融合評価関数

テストデータが用意できた次は、librosaを用いて音声の特徴量を抽出します。librosaはPythonにおける音声解析のデファクトスタンダードであり、テンポ（BPM）やスペクトル重心（音の明るさ）などを簡単に算出できます。

今回のPhase 2では、単純に音声の数値データを解析するだけでなく、ファイル名やタグなどの「文字列情報」と組み合わせて評価を行う「軸B/C融合評価関数」を実装しました。これにより、実測した音響特徴量とメタデータの双方を重み付けして判定できるようになります。

```python
import librosa

def analyze_audio_features(file_path):
    """librosaを用いてオーディオの特徴量を抽出する"""
    y, sr = librosa.load(file_path)
    
    # テンポ（BPM）の推定
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    # スペクトル重心（音の明るさの指標）
    cent = librosa.feature.spectral_centroid(y=y, sr=sr)
    
    return {
        "tempo": float(tempo),
        "spectral_centroid_mean": float(cent.mean())
    }

def fusion_evaluation(features, meta_string, weights):
    """
    軸B（実測データ）と軸C（文字列情報）を融合して評価する関数
    """
    score = 0
    
    # 軸B: 実測値に基づく評価（例: テンポが速いほどスコアアップ）
    if features["tempo"] > 120:
        score += weights.get("fast_tempo", 1.0)
        
    # 軸C: 文字列情報に基づく評価
    if "低音" in meta_string:
        score += weights.get("bass_keyword", 2.0)
        
    return score
```

重み（`weights`）を調整可能にすることで、解析ロジックを変更することなく、評価の基準を柔軟にチューニングできるのが特徴です。これにより、「低音が含まれている楽曲かどうか」「テンポが適切か」といった複合的な条件判定を簡単にテストできます。

## E2Eテストへの組み込みとCLI統合

生成したテストフィクスチャと評価関数を、実際のシステムに組み込むための仕組み作りを行いました。

具体的には、CLIツールに `--audio` オプションを追加し、このオプションが指定された際にlibrosaによる解析パイプラインが実行されるようにしました。これにより、開発者はコマンドライン一つで、任意の音声ファイルに対する解析と評価を試すことができます。

さらに、このパイプライン全体を流すE2Eテストを2件追加しました。例えば、先ほど生成した「祭礼前夜」パターンのフィクスチャを流し込み、安全判定が正しく行われるかや、v2の警告判定が期待通りに機能するかを検証しています。

テストを自動化する上で嬉しかったのは、CI/CD環境上でもwav生成からlibrosa解析まで一貫して実行できる点です。外部のAPIキーを用意しなくてもテストが完結するため、Pull Requestのたびに品質を担保できるようになりました。

## おわりに

本記事では、librosaを用いたオーディオ解析のE2Eテストを実現するための具体的なステップを紹介しました。

実データに依存しないwav生成テストフィクスチャの作成から、実測データと文字列情報を融合させる評価関数の設計、そしてCLIへの統合までをカバーすることで、堅牢なテスト環境を構築できました。オーディオ処理のテスト自動化にお悩みの方は、ぜひこのアプローチを参考にしてみてください。

これからもオーディオ解析の精度向上を図りながら、開発体験を向上させる取り組みを続けていきます。