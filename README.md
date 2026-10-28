# cd-rip-tagger

CDをドライブに入れた状態で商品ページのURL（BOOTH等）を渡すと、リッピング・MP3エンコード・タグ付け・ライブラリへの配置までを一括で行う Claude Code スキル。

gnudb / MusicBrainz / CTDB に未登録の同人CDが対象。曲目は外部DBではなく商品ページから取る。

## 何をするか

1. 光学ドライブを検出し、`.cda` スタブからトラック数と各トラックの長さを取得する（生アクセス不要。`cyanrip -I` はフォールバック）
2. Claude が商品ページを読んで、アルバム名・曲名・アーティスト・年・ジャケット画像URLを抽出する
3. 抽出したタグ一覧と出力先を**1回だけ**ユーザーに確認する
4. cyanrip で可逆圧縮（flac）に取り込み、ffmpeg でMP3にエンコードし、mutagen でタグを書いて配置する

出力先は `<ライブラリルート>/<アルバムアーティスト>/<アルバム名>/NN 曲名.mp3`。

## 必要なもの

- Windows（ネイティブ。WSL2 からは光学ドライブが見えない）
- **本体のコンソールセッション。** 光学ドライブへの生アクセスはコンソールセッションに
  割り当てられるため、リモートデスクトップ接続からは拒否される。コンソールであれば管理者権限は
  不要。リモートのまま使いたい場合は、管理者として起動したセッションでなら動く。スキルは
  ドライブを実際に開いて確かめ、できなければページの抽出に進む前に停止する。設定・ディスク情報の
  取得・出力計画の確認（`setup` / `probe` / `plan` / `run --dry-run`）は、リモートでも動く
- Python 3.9 以上
- [cyanrip](https://github.com/cyanreg/cyanrip)（CDリッパー）
- ffmpeg（libmp3lame 入りのビルド）
- Python パッケージ `mutagen`

cyanrip・ffmpeg・mutagen は、承認を取った上でスキルが自動取得できる。`%LOCALAPPDATA%\cd-rip-tagger\bin` に置かれ、PATH は汚さない。

```
python scripts/rip_and_tag.py check-deps --drive E:                   # 不足・導入計画・取り込めるかを確認
python scripts/rip_and_tag.py install-deps --accept cyanrip,mutagen   # 承認したものだけ取得
```

`check-deps` の `can_rip` は、ドライブを実際に開いて生アクセスできるかを試した結果。`false` なら `blocker` に理由が入る。光学ドライブが複数あって特定できない場合は `null` になるので、`--drive` を付けて実行する。

自分で用意する場合は、`cyanrip.exe` と `ffmpeg.exe` を PATH に置き、`pip install mutagen` する。

## 導入

```
npx skills add https://github.com/lsetzl/cd-rip-tagger
```

## 設定

初回実行時に、ライブラリルートとエンコード品質を聞いて `%APPDATA%\cd-rip-tagger\config.json` に保存する。スキル本体を更新しても消えない。

```
python scripts/rip_and_tag.py setup                                        # 現在の設定と選択肢を表示
python scripts/rip_and_tag.py setup --library-root "D:\Music" --quality v2 # 保存・変更
python scripts/rip_and_tag.py setup --drive-offset 667                     # ドライブオフセット
```

| 品質 | 内容 |
|------|------|
| `v0` | VBR V0（最高品質・約245kbps） |
| `v2` | VBR V2（推奨・約190kbps） |
| `cbr320` | CBR 320kbps（固定ビットレート） |

`drive_offset` はドライブの読み取りオフセット（サンプル数、既定0）。cyanrip は実リップ時にこの値の明示を要求する。同人CDのタグ付けが目的なら0で足りるが、AccurateRip 水準の正確さが必要なら自分のドライブの値を入れる。

## 手動で実行する

Claude を通さずスクリプト単体でも動く。

```
python scripts/rip_and_tag.py drives                               # 光学ドライブ一覧
python scripts/rip_and_tag.py probe --drive E:                     # ディスク情報
python scripts/rip_and_tag.py plan --input album.json              # 出力計画（確認用）
python scripts/rip_and_tag.py run  --input album.json --dry-run    # 取り込まず計画だけ表示
python scripts/rip_and_tag.py run  --input album.json --overwrite  # 実行
```

`plan` と `run` は、保存した設定を一時的に上書きできる。本番のライブラリを汚さずに試すときに使う。

```
python scripts/rip_and_tag.py run --input album.json --library-root D:\tmp --quality v0
```

他に `--disc-track-count N`（ディスク情報の取得を省いてトラック数を手で渡す）、`--no-probe`、`run` の `--work-dir` / `--keep-work-dir`（中間ファイルを残して調べる）がある。

`album.json` の形式は [SKILL.md](SKILL.md) の手順4を参照。出力はすべて UTF-8 のJSON（進捗ログは標準エラー出力）。エラーは `{"error": "..."}` を返して終了コード1。

## 仕様

タグは **ID3v2.3 + UTF-16** で書き、ID3v1 は書かない。日本語が化けにくい組み合わせ。

書き込むタグ：アルバム名（TALB）、アルバムアーティスト（TPE2）、曲名（TIT2）、トラック番号（TRCK、`N/総数`）、アーティスト（TPE1、無ければアルバムアーティストで埋める）、年（TYER）、ジャケット画像（APIC、フロントカバー）。`folder.jpg` は置かない。

フォルダ名・ファイル名に使えない文字 `\ / : * ? " < > |` は全角の同等文字に置き換え、末尾のドットと空白を除去する。Windows の予約名（CON, NUL など）は先頭に `_` を付ける。置換はファイル名側だけで、タグの中身は原文のまま。

取り込みが途中で失敗した場合、この実行で新しく作ったMP3は削除する。`--overwrite` で上書きしたファイルは元に戻せないため残し、何が残ったかを標準エラー出力に出す。

## 対象外

- MP3 以外の出力形式
- 複数枚組（1枚ずつ処理する）
- MusicBrainz への登録
- gnudb / Gracenote からの曲名取得

## 開発

```
pip install pytest mutagen
python -m pytest tests -q
```

実CDは不要。ffmpeg が無い環境ではエンコード関連のテストはスキップされる。
