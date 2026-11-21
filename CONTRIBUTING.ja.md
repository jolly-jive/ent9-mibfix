# 貢献のしかた

[English](CONTRIBUTING.md)

関心を持っていただきありがとうございます。Issue もプルリクエストも歓迎します。英語でも日本語でも構いません。

## Issue

**Problem report** のフォームを使ってください。機器、cisco-mibs と ent9-mibfix のコミット、
実行したコマンドを書く欄があります。

**snmpwalk をそのまま貼らないでください。** 値にも OID にも、ホスト名・アドレス・シリアル番号が
入っています。代わりに `extract_mibs.py ... --report FILE` が書くファイルを、中身を確認してから
添付してください（[README](README.ja.md) の「Issue で walk を共有する」を参照）。ファイルの一覧も
貼らないでください。パスにユーザー名が入っています。

セキュリティの問題は Issue ではなく [SECURITY.ja.md](SECURITY.ja.md) の方法で報告してください。

このツールがまだ直していない Cisco の MIB の誤りも、ここで受け付けます。上流で直してもらうには、
README の「Cisco への報告」を見てください。cisco/cisco-mibs は Issue を受け付けていません。

## プルリクエスト

- Python 3.8 以降、標準ライブラリだけを使います。
- テストを実行してください：`python3 -m unittest discover tests`。GitHub Actions が Linux と
  Windows で実行します。新しい動作にはテストを追加してください。テストは実物の MIB や walk ではなく、
  小さな MIB と walk を作って使います。
- GitHub Actions は `ruff check .` も実行します（ルールは `ruff.toml`、バージョンは
  `.github/lint-requirements.txt`）。ruff があれば push の前に実行してください。
- `fix_cisco_mibs.py` か `smiscan.py` を変えたときは、`tools/check_fix_output.py` で出力を比べて
  （README の「開発」を参照）、何が変わったかをプルリクエストに書いてください。
- コードのコメントとメッセージは英語です。文書は英語と日本語の両方（`README.md` と `README.ja.md`）に
  書きます。片方しか書けない場合はそう書いてください。もう片方はこちらで追加します。
- MIB ファイル、walk、実際のネットワークから取ったものは、絶対にコミットしないでください。MIB は
  Cisco のものです。そのため `cisco-mibs/`、`out/`、`samples/` は git の対象外にしています。

貢献していただいたものは、プロジェクトのほかの部分と同じく [Apache License 2.0](LICENSE) で
ライセンスされます。
