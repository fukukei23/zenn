---
title: "【Python】yt-dlp + basic_pitchで音楽分析CLIを作った：mp3→MIDI→特徴量抽出のパイプライン構築"
emoji: "🎵"
type: "tech"
topics: ["python", "cli", "librosa", "ytdlp", "音楽分析"]
published: false
---

# はじめに

「お気に入りの楽曲のコード進行やBPM、メロディの特徴をサクッと知りたい」と思ったことはありませんか？
DAW（音楽制作ソフト）を開いて耳コピするのは時間がかかりますし、いきなり高度な音楽理論を学ぶのはハードルが高いです。

そこで本記事では、**YouTube等の音源を取得し、自動でMIDI変換や音楽的特徴量（BPM・キー・メロディ音域など）を抽出してレポートを出力するCLIツール**の構築手順を解説します。

使用する技術スタックは以下の通りです。
- **yt-dlp**: 音源取得（YouTube等からのダウンロード）
- **basic_pitch**: MP3からのMIDI自動変換（Spotify製のAIモデル）
- **librosa**: 音響信号処理（BPMやキーの推定）
- **MuseScore**: 楽譜（PNG/PDF）のレンダリング

実務での開発プロセス（タスク分割から統合まで）を意識しながら、エラーハンドリングやフォールバック（代替処理）の設計にも触れていきます。

# 全体アーキテクチャと音源取得の自動化

## パイプラインの設計

このCLIツールは、1つの巨大なスクリプトにするのではなく、機能ごとに細かくタスク（モジュール）に分割して設計しました。実際の開発（コミット履歴）でも、以下のようにタスクを分けて実装を進めています。

1. **source_fetch**: `yt-dlp` を使った音源取得
2. **tempo_key**: `librosa` によるBPM・再生時間の抽出
3. **midi_extract**: `basic_pitch` によるMP3→MIDI変換
4. **features**: キー・コード推定、メロディ音域、楽曲構造の分析
5. **score_render**: `MuseScore` による楽譜画像の生成
6. **report**: 抽出したデータをMarkdown形式のレポートにまとめる

各タスクの出力（JSONやMIDIファイル）を次のタスクが受け取るパイプライン設計にすることで、一部の処理が失敗しても全体は止まらずにスキップするような堅牢な設計が可能になります。

## yt-dlpによる音源取得とフォールバック

まずは音源の取得です。今回は `yt-dlp` を利用してYouTubeから音声をMP3形式でダウンロードします。
もしURL指定がなかったり、ネットワークエラーでダウンロードに失敗した場合は、ローカルのMP3ファイルを参照するようなフォールバック（代替処理）を組み込みます。

```python
import subprocess
from pathlib import Path

def fetch_audio_source(url: str, output_path: str = "temp/input.mp3") -> Path:
    """
    yt-dlpを用いてURLから音源を取得し、MP3として保存する。
    失敗した場合は例外を投げず、呼び出し元でローカルファイルのフォールバックを促す。
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if not url:
        raise ValueError("URLが指定されていません。ローカルファイルを利用してください。")

    # yt-dlpのコマンドを組み立て
    command = [
        "yt-dlp",
        "-x",  # 音声のみ抽出
        "--audio-format", "mp3",
        "-o", str(out_file),
        url
    ]

    try:
        print(f"Downloading audio from: {url}")
        subprocess.run(command, check=True, capture_output=True, text=True)
        
        if out_file.exists():
            print("Download complete.")
            return out_file
        else:
            raise FileNotFoundError("yt-dlpは成功しましたが、ファイルが見つかりません。")
            
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] yt-dlpでの取得に失敗しました: {e.stderr}")
        raise RuntimeError("音源のダウンロードエラー。ローカルファイル処理に切り替えてください。")
```

`subprocess.run` の `capture_output=True` を使うことで、エラー時の標準エラー出力（stderr）を捕捉し、ログに残す実務的なエラーハンドリングを行っています。

# AIによるMP3→MIDI変換と特徴量抽出

## basic_pitchでメロディをMIDI化

次に、ダウンロードしたMP3をMIDIデータに変換します。ここではSpotifyが開発した `basic_pitch` を使用します。機械学習モデルが音声を解析し、ボーカルや楽器の音程をノート情報として書き出してくれます。

```python
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

def extract_midi(audio_path: str, midi_path: str):
    """
    basic_pitchを用いて、音声ファイルからMIDIを生成する。
    """
    print("MP3からMIDIを抽出中... (数秒〜数十秒かかります)")
    
    # basic_pitchのモデルを読み込んで予測
    model_output, midi_data, _ = predict(audio_path, ICASSP_2022_MODEL_PATH)
    
    # MIDIファイルとして保存
    midi_data.write(midi_path)
    print(f"MIDI saved to: {midi_path}")
    return midi_path
```

この処理をTask4として独立させることで、BPM取得（Task3）が失敗していてもMIDI抽出（Task4）は実行できる、というようなモジュール間の非依存性を保つことができます。

## librosaによる楽曲分析とレポート生成

MIDIが生成できたら、次は `librosa` を使ってBPMやキー（調性）を推定し、さらにMIDIデータから「メロディの音域」や「フレーズの繰り返し（phrase_repetition）」といった特徴量を抽出します。

ここでの工夫点は、**「エラーの中央管理」**です。
MuseScoreによる楽譜画像の生成（Task6）は、ユーザーのPCにMuseScoreがインストールされていないと失敗します。しかし、画像生成ができなくてもテキストのレポート（Task7）は出力したいですよね。

そのため、CLI全体を統合するパイプライン（Task8）にて、各モジュールの例外を一元管理し、エラーが起きたタスクは「スキップ」として扱い、最終的な `features.json` には `null` やエラーメッセージを格納する設計にしました。

集めた特徴量は、最終的に以下のようなMarkdownレポートとして出力されます。

```markdown
# 🎵 音楽分析レポート

- **BPM**: 128.5
- **推定キー**: C Major
- **メロディ音域**: C4 〜 G5
- **コード進行**: Am - F - C - G
```

# 実務で役立つポータビリティ向上の工夫

ツールを自分以外の人（あるいは別の環境）でも使えるようにするため、設定ファイルのハードコード除去を行いました。これは実際の開発でもPR（Pull Request）を立てて対応した部分です。

## ハードコードされたパスの除去

最初の実装では、自分のWSL（Windows Subsystem for Linux）環境のユーザー名が `/home/username/` とベタ書き（ハードコード）されていました。これでは他のPCに移行した際にパスエラーで動かなくなってしまいます。

そこで、以下のように環境変数を活用した動的なパス解決に変更しました。

- **Python**: `Path("~/.claude/logs").expanduser()` を使い、チルダ（~）を展開
- **Bashスクリプト**: `$HOME` 変数を使用
- **PowerShell**: `$env:USERPROFILE` 変数を使用

```python
import os
from pathlib import Path

# 悪い例（ハードコード）
# LOG_DIR = Path("/home/username/.claude/logs")

# 良い例（ポータブルな記述）
LOG_DIR = Path(os.environ.get("LOG_DIR", "~/.claude/logs")).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
```

このような「環境依存をなくす」設計は、チーム開発やOSS公開において非常に重要です。Pythonの `pathlib` と `os.environ` を組み合わせることで、WindowsでもMac/Linuxでもシームレスに動作するCLIツールが完成しました。

# おわりに

本記事では、`yt-dlp`、`basic_pitch`、`librosa` を組み合わせて、音源取得から特徴量抽出、レポート生成までを自動化するCLIツールの構築事例を紹介しました。

タスクを細かく分割してパイプラインを構築することで、エラーに強く保守性の高いツールを作ることができます。また、パスのハードコード除去など、少しの工夫でツールの汎用性は劇的に上がります。

「音楽データをプログラムで解析してみたい」という方は、ぜひ `basic_pitch` や `librosa` を触ってみてください。コードを書くだけで自動で耳コみをしてくれる感覚は非常に面白いです。

この記事が、PythonでのCLIツール開発や音楽分析のヒントになれば幸いです！