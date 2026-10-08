# Voiceger Editor 日本語ドキュメント

## はじめに

初めて使用する場合は、次の順に参照してください。

1. [セットアップ](<setup.md>)  
   Voiceger Editor のインストールと動作確認
2. [はじめての音声生成](<tui.md>)  
   Caption の追加から Take の生成・採用までの基本操作

基本的な操作の流れは次のとおりです。

``` text
Caption を追加
→ 発音を確認
→ Take を生成
→ Take を再生
→ Take を採用
→ 音声ファイルを保存
```

## ドキュメント

- [BATCH LIST](<batch-list.md>)  
  Caption の追加・管理、一括生成、バッチファイルの読み書き
- [BATCH ITEM](<batch-item.md>)  
  Caption ごとの発音確認、Take の生成・再生・再生成・採用
- [発音編集](<pronunciation.md>)  
  日本語の読みとアクセント、英語の発音、日英混在文の編集
- [ARPAbet](<arpabet.md>)  
  ARPAbet の表記と入力例
- [ユーザー辞書](<dictionary.md>)  
  日本語・英語辞書の登録、編集、インポート・エクスポート
- [設定](<settings.md>)  
  Style、Speed、Take 数、保存先、音声形式、TXT / LAB などの設定
- [LAB 出力](<lab.md>)  
  LAB 出力の設定、必要な環境、制限事項
- [MP3 出力](<mp3.md>)  
  MP3 出力の設定と必要な環境
- [HTTP API](<http-api.md>)  
  HTTP API のインストールと使用方法
- [互換性](<compatibility.md>)  
  対応する Voiceger、Python、OS と既知の制限

## 対応する文章

Voiceger Editor 0.1 では、次の文章を扱えます。

- 日本語
- 英語
- 日本語と英語が混在する文章

日本語では読みとアクセント、英語では ARPAbet と強勢を編集できます。

## Voiceger

Voiceger Editor を使用するには、Voiceger を別途インストールする必要があります。

Voiceger Editor には Voiceger 本体、モデル、参照音声は含まれていません。

## 生成音声とライセンス

Voiceger Editor で生成した音声には、[Voicegerずんだもん音源利用規約](<https://zunko.jp/con_ongen_kiyaku.html>)が適用されます。

Voiceger Editor のライセンスについては、リポジトリの [README](<../../README.md>) を参照してください。
