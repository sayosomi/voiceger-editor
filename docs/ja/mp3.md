# MP3出力

Voiceger Editorでは、採用したTakeをMP3形式で保存できます。

MP3出力はオプション機能です。初期設定ではWAV形式が選択されています。

## 必要な環境

MP3出力には、外部プログラムの**FFmpeg**が必要です。

FFmpegはVoiceger Editorに同梱されていないため、別途インストールしてください。

### macOS

Homebrewを使用している場合は、ターミナルで次のコマンドを実行します。

```bash
brew install ffmpeg
```

Homebrewを使用していない場合は、[FFmpeg公式サイト](https://ffmpeg.org/download.html)から導入方法を確認してください。

### Windows

[FFmpeg公式サイト](https://ffmpeg.org/download.html)からWindows向けの配布先を確認し、FFmpegをインストールしてください。

インストール後は、`ffmpeg.exe` がコマンドラインから実行できるようにPATHを設定する必要があります。

### Linux

使用しているLinuxディストリビューションのパッケージマネージャーからFFmpegをインストールしてください。

例えばUbuntuやDebianでは、次のコマンドを使用できます。

```bash
sudo apt install ffmpeg
```

### インストールの確認

ターミナルで次のコマンドを実行します。

```bash
ffmpeg -version
```

FFmpegのバージョン情報が表示されれば、コマンドラインから利用できる状態です。

コマンドが見つからない場合は、FFmpegのインストール先やPATHの設定を確認してください。

インストール後もVoiceger EditorにMP3が表示されない場合は、Voiceger Editorを終了し、ターミナルから起動し直してください。

## MP3出力を有効にする

1. `BATCH LIST`で`S`キーを押し、`EDIT SETTINGS`を開きます。
2. `[O] File format & naming` から `AUDIO OUTPUT` を開く。
3. `Format` を `MP3` に変更する。
4. `Bitrate` を選択する。
5. `EDIT SETTINGS` に戻り、`[A] Apply and save` で設定を保存する。

設定画面については、[設定](settings.md)を参照してください。

### Bitrate

MP3では、次のビットレートから選択できます。

| Bitrate  |
| -------- |
| 96 kbps  |
| 128 kbps |
| 160 kbps |
| 192 kbps |
| 256 kbps |
| 320 kbps |

初期値は`192 kbps`です。

ビットレートを高くすると、一般的に音質を維持しやすくなりますが、ファイルサイズは大きくなります。

低くするとファイルサイズを小さくできますが、音質が低下する場合があります。

## MP3が生成されるタイミング

Voiceger Editorでは、**Takeを生成した時点ではWAV形式の音声が作成されます。**

MP3への変換は、Takeを採用して保存するときに行われます。

```text
Takeを生成
↓
WAVでプレビュー・再生
↓
Takeを採用
↓
FFmpegでMP3へ変換
↓
MP3ファイルを保存
```

したがって、MP3を選択しても、候補Takeや発音プレビューの音声形式は変わりません。

## 保存されるファイル

例えば「今日は雨なのだ。」のTakeをMP3形式で採用すると、次のようなファイルが保存されます。

```text
202610020307_Neutral_今日は雨なのだ。.mp3
```

TXT出力が有効な場合は、同じ名前のTXTファイルも保存されます。

```text
202610020307_Neutral_今日は雨なのだ。.txt
```

LAB出力が有効な場合は、MP3形式でもLABを生成できます。

```text
202610020307_Neutral_今日は雨なのだ。.lab
```

LAB生成には内部的にWAVを使用するため、保存する音声がMP3でも時刻合わせを実行できます。

ただし、LAB出力には追加の環境と制限事項があります。詳しくは[LAB出力](lab.md)を参照してください。

ファイル名の変更や保存先については、[設定](settings.md)を参照してください。

## FFmpegが使用できない場合

FFmpegが見つからない場合、`AUDIO OUTPUT` の`Format`にはMP3が表示されません。

この場合でも、Voiceger Editorの起動やWAV・FLAC出力は通常どおり使用できます。

以前MP3を選択して保存していた場合でも、FFmpegが使用できない環境で設定を読み込むと、音声形式はWAVに切り替わります。

MP3のビットレート設定は保持されます。

## MP3変換に失敗した場合

FFmpegの実行に失敗した場合、Voiceger Editorはエラーを通知します。

保存に失敗したMP3ファイルや、同時に保存しようとしたTXTファイルの不完全な出力は削除されます。

元の候補TakeのWAVは、MP3への変換によって変更されません。

FFmpegが正常にインストールされているか、保存先に書き込み権限があるかなどを確認してください。

## HTTP APIについて

HTTP APIの`/synthesis`はWAV音声を返します。

`AUDIO OUTPUT`でMP3を選択しても、HTTP APIの応答形式は変わりません。

MP3出力は、TUIでTakeを採用してファイルに保存する際の機能です。
