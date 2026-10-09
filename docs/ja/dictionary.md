# ユーザー辞書

Voiceger Editorでは、よく使う単語や自動変換で正しく発音されない単語をユーザー辞書に登録できます。

日本語と英語にそれぞれ独立した辞書があります。

登録した単語は発音情報を自動作成する際に利用されます。

## 辞書を開く

`BATCH LIST` または `BATCH ITEM` で、`[D] Dictionary` を選択します。

`DICTIONARY` 画面には次の項目があります。

| 項目 | 内容 |
|---|---|
| `[J] Japanese` | 日本語辞書 |
| `[E] English` | 英語辞書 |
| `[I] Import dictionary` | 辞書のインポート |
| `[X] Export dictionary` | 辞書のエクスポート |

## 単語を登録する

### 日本語辞書

`DICTIONARY` で `[J] Japanese` を開き、`[A] Add` を選択します。

`ADD JAPANESE DICTIONARY WORD` が開き、`Surface` の入力がすぐに始まります。

日本語辞書では、次の項目を設定できます。

| 項目 | 内容 |
|---|---|
| Surface | 登録する単語の表記 |
| Pronunciation | カタカナによる読み、アクセント位置 |
| Word type | 品詞 |
| Priority | 優先度 |

#### Surface

辞書で一致させたい単語を入力します。

例えば、次のような固有名詞を登録できます。

```text
ずんだもん
```

#### Pronunciation

`[G] Generate pronunciation` で、Surfaceから発音情報を自動作成できます。

作成された発音情報は、必要に応じて修正できます。

`Pronunciation` にフォーカスを合わせると、Left / Rightでアクセント位置を変更できます。Enterでは読みを直接編集できます。

日本語辞書には、**1つのアクセント句からなる発音**を登録します。

日本語の読みやアクセントの表記については、[日本語の発音編集](japanese-pronunciation.md)を参照してください。

#### Word type

登録する単語の品詞を選択します。

Voiceger Editorでは、次の5種類を使用できます。

| 品詞 | 用途の例 |
|---|---|
| 固有名詞 | 人名・地名・作品名など |
| 普通名詞 | 一般的な名詞 |
| 動詞 | 動作を表す言葉 |
| 形容詞 | 性質や状態を表す言葉 |
| 接尾辞 | 語の後ろに付く言葉 |

初期値は「固有名詞」です。

Left / Rightで切り替えられます。

#### Priority

単語の優先度を設定します。

設定できる範囲は `0〜10`、初期値は `5` です。

通常は初期値のままで構いません。

Left / Rightで変更できます。

#### 発音を確認して保存する

`[P] Preview` で登録前の発音を確認できます。

問題がなければ `[S] Save` を実行します。

同じSurfaceに複数の登録候補がある場合は、更新する既存エントリを選択する画面が表示されることがあります。

### 英語辞書

`DICTIONARY` で `[E] English` を開き、`[A] Add` を選択します。

`ADD ENGLISH DICTIONARY WORD` が開き、`Surface` の入力がすぐに始まります。

英語辞書には次の項目を登録します。

| 項目 | 内容 |
|---|---|
| Surface | 登録する英単語 |
| Pronunciation | ARPAbetによる発音 |

例えば、`sweet` なら次のように指定します。

**Surface**

```text
sweet
```

**Pronunciation**

```text
S W IY1 T
```

`[G] Generate pronunciation` で、SurfaceからARPAbetを自動作成できます。

その後、必要に応じて修正します。

`Pronunciation` にフォーカスを合わせると、Left / Rightで第一強勢を移動できます。EnterではARPAbetを直接編集できます。

`[P] Preview` で確認し、`[S] Save` で登録します。

ARPAbetの記号と強勢については、[英語の発音編集（ARPAbet）](arpabet.md)を参照してください。

英語辞書では、単語の大文字・小文字を区別せずに照合します。

## 登録済みの単語を管理する

日本語・英語の辞書一覧では、登録済みの単語を確認できます。

### 単語を編集する

編集したい単語を選択してEnterを押すと、編集画面が開きます。

内容を変更し、`[S] Save` で保存します。

保存していない変更がある状態で画面を離れようとすると、変更を破棄するか確認されます。

### 単語を削除する

辞書一覧で削除したい単語にフォーカスを合わせ、`[X] Delete` を実行します。

編集画面から削除することもできます。

削除前には確認画面が表示されます。

`[D] Delete` で確定し、Escでキャンセルできます。

### 番号で単語を選択する

辞書一覧では、番号キーで単語を直接選択できます。

1〜9番目の単語は、対応する数字キーで開けます。

表示中の単語が10件以上ある場合は、`0` で番号入力を開けます。

番号を入力してEnterで移動し、Escでキャンセルできます。

### Sort：表示順を変更する

辞書一覧の `[S] Sort` では、表示順を変更できます。

Sortの行でLeft / Rightを押すか、Sortの選択画面から並び順を指定します。

日本語辞書では、次の並び順を使用できます。

| 表示順 | 内容 |
|---|---|
| Surface ↑ | 表記の昇順 |
| Surface ↓ | 表記の降順 |
| Word type | 品詞順 |
| Priority ↑ | 優先度の昇順 |
| Priority ↓ | 優先度の降順 |
| Added ↑ | 登録順の昇順 |
| Added ↓ | 登録順の降順 |

英語辞書では、Surfaceの昇順・降順と、登録順の昇順・降順を使用できます。

Sortは一覧の表示順を変更する機能です。辞書ファイルに保存されている単語の順序は変更しません。

### Filter：単語を絞り込む

`[F] Filter` では、条件に一致する単語だけを表示できます。

日本語辞書では、次の条件を使用できます。

- SurfaceまたはPronunciationの文字列
- Word type（品詞）

英語辞書では、SurfaceまたはARPAbetの文字列で検索できます。

条件を設定して `[A] Apply` を実行すると、一覧が絞り込まれます。

一度条件を設定した後は、辞書一覧のFilter行でLeft / Rightを押すことで、**条件を保持したままフィルターの有効・無効を切り替えられます。**

条件自体を削除したい場合は、Filter編集画面の `[C] Clear filter` を使用します。

## 発音編集画面から辞書に登録する

`BATCH ITEM` の `EDIT PRONUNCIATION` には、`[S] Save to dictionary` があります。

これを使用すると、現在の発音情報を引き継いだ状態で辞書登録画面を開けます。

例えば、何度も使う固有名詞の発音を調整した場合、その結果を辞書に登録しておくと便利です。

日本語では、日本語辞書に登録できる形式の発音情報が必要です。

## 辞書をインポートする

`DICTIONARY` で `[I] Import dictionary` を選択します。

Voiceger Editorでは、既存の辞書ファイルを読み込み、登録する項目を確認してからインポートできます。

### 対応形式

次のJSON形式に対応しています。

| 形式 | 内容 |
|---|---|
| VOICEVOX日本語辞書 | UUIDをキーとするUserDictWord形式 |
| Voiceger Editor日本語辞書 | VOICEVOX互換のJSON形式 |
| Voiceger Editor英語辞書 | 英単語とARPAbetの対応を保存したJSON形式 |

日本語のVOICEVOX辞書は、事前に変換せずインポートできます。

辞書形式はファイル名ではなく、JSONの内容から判定されます。

### ファイルを読み込む

`IMPORT DICTIONARY` の `File path` にJSONファイルのパスを入力します。

初期値には、設定済みのOutputディレクトリが使用されます。

ここで入力するのは読み込み元ファイルのパスです。変更しても、音声やエクスポートファイルの保存先は変わりません。

パスを指定したら、`[I] Review file` を実行します。

### インポート内容を確認する

ファイルを読み込むと、登録候補を確認する画面が開きます。

候補は、既存の辞書との比較結果によって扱いが変わります。

| 判定 | 初期状態 |
|---|---|
| 新規登録 | 選択済み |
| 既存の登録と競合 | 未選択 |
| 完全一致する登録 | 候補一覧から除外 |

競合する項目には、チェックボックスの直後に `!` が表示されます。

Spaceで選択状態を切り替えられます。

候補を選択してEnterを押すと、詳細を確認できます。

日本語の詳細画面では、Surface・Pronunciation・Accent・Word type・Priorityを確認できます。この画面で変更できるのはWord typeのみです。

英語の詳細画面は確認専用です。

インポートする項目を選択したら、`[I] Import selected` を実行します。

`[C] Clear selection` では、すべての候補の選択を解除できます。

インポートを確定せずに戻った場合、辞書は変更されません。

インポート完了後は、追加・置換・スキップした件数が表示されます。

## 辞書をエクスポートする

`DICTIONARY` で `[X] Export dictionary` を選択します。

エクスポートには次の2種類があります。

### Voiceger Editor形式

`[E] Voiceger Editor` を選択すると、日本語辞書と英語辞書を別々のJSONファイルに出力します。

ファイル名の例：

```text
YYYYMMDDHHMM_user_dict.json
YYYYMMDDHHMM_english_user_dict.json
```

2つの辞書をまとめた単一ファイルではありません。

### VOICEVOX形式

`[V] VOICEVOX` を選択すると、日本語辞書だけをVOICEVOX互換のJSONファイルとして出力します。

ファイル名の例：

```text
YYYYMMDDHHMM_voicevox_user_dict.json
```

英語辞書は含まれません。

### 保存先とファイル名

エクスポート先は、Voiceger Editorで設定されているOutputディレクトリです。

`[F] Output` から保存先を変更できます。この変更は共通のOutput設定に反映されます。

保存先の設定については、[設定](settings.md)を参照してください。

エクスポート時に同名ファイルが存在しても、既存ファイルは上書きされません。

ファイル名の末尾に `-2`、`-3` などを追加して保存します。

Voiceger Editor形式で2ファイルを同時に出力する場合は、両方に同じ番号が付けられます。

## 辞書ファイルの保存場所

ユーザー辞書は、Voiceger Editorの設定ファイルと同じディレクトリに保存されます。

| 辞書 | ファイル名 |
|---|---|
| 日本語辞書 | `user_dict.json` |
| 英語辞書 | `english_user_dict.json` |

OSごとの標準保存先は次のとおりです。

**macOS**

```text
~/Library/Application Support/voiceger-editor/
```

**Windows**

```text
%APPDATA%\voiceger-editor\
```

**Linux**

```text
~/.config/voiceger-editor/
```

Windowsで`APPDATA`が利用できない場合や、Linuxで`XDG_CONFIG_HOME`が設定されている場合などは、保存場所が変わることがあります。

これらはVoiceger Editorが管理するファイルであり、Voiceger本体のリポジトリ内には保存されません。

## HTTP APIからの辞書操作

ユーザー辞書は、HTTP APIからも操作できます。

日本語辞書にはVOICEVOX互換の辞書APIがあります。

英語辞書にはVoiceger Editor独自のAPIが用意されています。英語辞書APIはVOICEVOX互換ではありません。

詳しくは[HTTP API](http-api.md)を参照してください。

## 関連ドキュメント

- [日本語の発音編集](japanese-pronunciation.md) — 日本語の読みとアクセント
- [英語の発音編集（ARPAbet）](arpabet.md) — ARPAbetと強勢
- [BATCH ITEM](batch-item.md) — Captionと発音情報の編集
- [設定](settings.md) — 共通のOutputディレクトリ
- [HTTP API](http-api.md) — APIからの辞書操作
