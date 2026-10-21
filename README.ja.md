# <img src="icon.svg" alt="" width="40" height="40" align="middle"> ent9-mibfix

[English](README.md)

Cisco 公式の MIB リポジトリ [cisco/cisco-mibs](https://github.com/cisco/cisco-mibs) の `v2/` を、
**依存関係が閉じていて、エラーなく読み込める MIB セット**に変換するスクリプトです。

`v2/` をそのまま読み込むと、大量のエラーが出ます。import 先のモジュールが無い、
ファイル名とモジュール名が合わない、MIB 本文に構文の誤りがある、などが原因です。
昔から知られている問題で、今も上流では直っていません。

**このリポジトリには Cisco の MIB は含まれていません。** Cisco のリポジトリは各自で clone し、
手元で変換してください。

このプロジェクトは Cisco Systems とは関係がなく、Cisco の承認を受けたものでもありません。

## 直すもの

件数は上流のコミット `c9ab98c`（2026-09-29）で実行した場合のものです。

1. **`v2/` に無い依存先**（17 モジュール追加）
   `TOKEN-RING-RMON-MIB` などは `v1/` にしかありません。これが無いと `RMON2-MIB` が壊れ、
   それを import する 126 モジュールも巻き添えになります。`v1/` から補い、Cisco が配布していない
   標準 MIB は、指定されたディレクトリから補います。
2. **`v1/` にしかない OLD-CISCO-\* モジュール**（15 モジュール追加）
   `OLD-CISCO-INTERFACES-MIB` や `OLD-CISCO-CPU-MIB` など、`enterprises.9.2`（`local`）を定義するものです。
   今の IOS や IOS-XE もこれに応答します（Catalyst 3850 では約 16,000 OID）。`v1/` からそのままコピーします。
3. **ファイル名とモジュール名の不一致、モジュールの重複**（15 ファイル改名、13 モジュールの重複を解消）
   すべて `<モジュール名>.my` で出力します。同じモジュールが複数ファイルにある場合は、
   `LAST-UPDATED` が新しい方を採用します。
4. **import 漏れ**（27 モジュールに 37 件追加）
   `TruthValue` や `Counter32` などを使っているのに import していないもの。
5. **MIB 本文の誤り**（35 件）
   文字列の閉じ忘れ、`END` の重複、末尾カンマ、型名の綴り誤り、名前の重複など。

すべての変更は `CHANGES.md`（英語）、`CHANGES.ja.md`（日本語）、`changes.json` に記録されます。
特定の箇所を狙った修正は、該当箇所が見つからなければ「適用されなかった修正」として記録されるので、
Cisco 側で直ったかどうかも分かります。

## 必要なもの

- Python 3.8 以上（標準ライブラリのみ）
- git
- `v2/` が import しているのに Cisco が配布していない標準 MIB。
  Net-SNMP と LibreNMS の `mibs/` ですべて揃います（下記）。

## 使い方

```sh
# Cisco の MIB
git clone --depth 1 https://github.com/cisco/cisco-mibs.git

# 標準 MIB：Net-SNMP と LibreNMS の mibs/ だけを取得
git clone --depth 1 --filter=blob:none --sparse https://github.com/net-snmp/net-snmp.git
git -C net-snmp sparse-checkout set mibs
git clone --depth 1 --filter=blob:none --sparse https://github.com/librenms/librenms.git
git -C librenms sparse-checkout set --no-cone '/mibs/*' '!/mibs/*/'

# 変換
python3 fix_cisco_mibs.py cisco-mibs out net-snmp/mibs librenms/mibs
```

```
fix_cisco_mibs.py CISCO_MIBS_REPO OUT_DIR [EXTRA_MIB_DIR ...]
```

| 引数 | 意味 |
|---|---|
| `CISCO_MIBS_REPO` | cisco/cisco-mibs を clone したディレクトリ。変更はしません |
| `OUT_DIR` | 出力先。既に存在する場合は中止します |
| `EXTRA_MIB_DIR` | リポジトリに無い標準 MIB を探すディレクトリ。複数指定できます。`v1/` を最初に探し、次にこれらを指定順に探します |

出力：

| パス | 内容 |
|---|---|
| `OUT_DIR/mibs/` | 修正済みの MIB。1 モジュール 1 ファイルで、ファイル名は `<モジュール名>.my` |
| `OUT_DIR/CHANGES.md` | 全変更の一覧（英語） |
| `OUT_DIR/CHANGES.ja.md` | 同じ内容の日本語版 |
| `OUT_DIR/changes.json` | 同じ内容の機械可読版（`detail` が英語、`detail_ja` が日本語） |

見つからなかったモジュールは、`CHANGES.md` の「未解決の依存」に出ます。

### 標準 MIB の入手先

コミット `c9ab98c` では、リポジトリの外から次の 7 モジュールが必要です。

| モジュール | 入手先 |
|---|---|
| RFC1155-SMI、RFC-1215 | Net-SNMP の `mibs/` |
| RFC-1212、RFC1271-MIB、DNS-SERVER-MIB、IANA-PRINTER-MIB、IANA-CHARSET-MIB | LibreNMS の `mibs/` |

これらのモジュールがあれば、他のディレクトリでも構いません。各ディレクトリの直下だけを探し、
ファイル名ではなくモジュール名で判別します。

### Net-SNMP で使う

```sh
snmpwalk -M +/path/to/out/mibs -m +CISCO-PROCESS-MIB -v2c -c public HOST cpmCPUTotalTable
```

常用するなら `~/.snmp/snmp.conf` に次を書きます。

```
mibdirs +/path/to/out/mibs
```

`out/mibs/` には、Net-SNMP 付属の標準 MIB と同名のモジュール（IF-MIB など）も含まれます。
両方を読み込むと `-Pw` で重複の警告が出ることがありますが、エラーにはなりません。

Net-SNMP 5.9 は既定では名前に `_` を受け付けず、一部の Cisco MIB は列挙ラベルに `_` を使っています
（CISCO-LWAPP-TC-MIB の `dot11_6ghz` など）。`-Pu` を付けるか、`snmp.conf` に
`mibAllowUnderline yes` を書いてください。

## 機器に必要な MIB だけを取り出す

`out/mibs/` には約 1,700 モジュールありますが、1 台の機器に必要なのはそのごく一部です。
`extract_mibs.py` は実機の `snmpwalk` を読み、Cisco の OID を名前にするのに必要な MIB ファイルを、
それらが import するモジュールも含めて列挙します。

```sh
# enterprises.9 ではなく enterprises から walk する（下記）。-On は必須
snmpbulkwalk -On -v2c -c public HOST 1.3.6.1.4.1 > walk.txt

python3 extract_mibs.py out/mibs < walk.txt
python3 extract_mibs.py out/mibs --exclude-dir /usr/share/snmp/mibs --archive c3850.zip < walk.txt
python3 extract_mibs.py out/mibs --load-order < walk.txt
python3 extract_mibs.py out/mibs --verify < walk.txt
```

```
extract_mibs.py MIB_DIR [MIB_DIR ...] [--prefix OID] [--exclude-dir DIR] [--archive FILE] [--load-order] [--verify]
```

| 引数 | 意味 |
|---|---|
| `MIB_DIR` | MIB のディレクトリ。通常は `out/mibs`。複数指定できます（Cisco が別に配布している MIB を足す場合など）。同じモジュールが複数にある場合は、先に指定した方を使います |
| `--prefix OID` | この OID 配下だけを対象にします。複数指定できます。既定は `1.3.6.1.4.1.9` と `1.3.6.1.4.1.14179` |
| `--exclude-dir DIR` | `DIR`（サブディレクトリを含む）に既にあるモジュールを除きます。Net-SNMP 付属の標準 MIB などに使います。複数指定できます |
| `--archive FILE` | ファイルを `FILE`（`.zip`、`.tar.gz`、`.tgz`、`.tar`）にもまとめます。中身はファイル名と同じ名前のフォルダに入ります |
| `--load-order` | 名前順ではなく、各ファイルを、それが import するモジュールの後になる順で列挙します。MIB を 1 つずつ読み込むマネージャや MIB ブラウザ向けです。`--archive` にも同じ順で格納します |
| `--verify` | 列挙したファイルで足りるかを Net-SNMP で確認します（下記）。足りなければ終了コード 1 で終わります |

walk は標準入力から読みます。必要なファイルのパスを 1 行に 1 つ標準出力に出し、
集計と、どの MIB にも定義が無い OID を標準エラーに出します。

- **`-On` を付けてください。** 数値の OID だけを読みます。シンボル形式（`SNMPv2-SMI::enterprises.9...`）
  の行があると、`-On` を付けて取り直すよう表示します。
- **`1.3.6.1.4.1` から walk してください。** Cisco の機器には `1.3.6.1.4.1.14179`（Airespace、
  今の Cisco の無線 MIB）配下にも応答するものがあります。たとえば Catalyst 3850 は無線コントローラ機能を
  内蔵していて、使っていなくても既定の設定値を返します。`1.3.6.1.4.1.9` だけを walk すると、これを見落とします。
- **どの MIB にも定義が無い OID** はサブツリーごとに表示します。公開 MIB に無いオブジェクトに応答する機器も
  あるので、多少出るのは正常です。Cisco Small Business の機器（`1.3.6.1.4.1.9.6.1.101`、CISCOSB-* MIB）は
  cisco-mibs に含まれていません。その MIB を別の `MIB_DIR` として追加してください。
- トラップは walk に現れません。トラップの解読にだけ必要な MIB は見つかりません。
- **`--load-order` を付けても、互いに import し合うモジュール**は、どのツールでも通る順には並べられません。
  名前順で隣り合わせに並べ、標準エラーに警告を出します。現在の cisco-mibs では `CISCO-LWAPP-AP-MIB` と
  `CISCO-LWAPP-DOT11-MIB` の組だけが該当します。名前順で AP が先になり、これで正しく読めます。
  DOT11 は AP のオブジェクトをテーブルのインデックスに使っていますが、AP は DOT11 のオブジェクトを 1 つ、
  通知の中で使っているだけだからです。

### 結果の確認（`--verify`）

`--verify` には `snmptranslate`（Net-SNMP）が必要です。列挙したファイル（と `--exclude-dir`）だけを
読み込み、walk のすべての OID が、`MIB_DIR` を全部読み込んだ時と同じ名前になるかを確認します。
walk をもう一度取る必要はありません。次の場合に失敗とします。

- 名前が変わる OID がある。たとえば `ciscoEnvMonFanState` ではなく `ciscoMgmt.13.1.4.1.3` になる場合です。
  オブジェクトごとに、代わりに付いた名前と一緒に表示します。
- 列挙したファイルだけの時に、`MIB_DIR` を全部読み込んだ時には出ない Net-SNMP の警告
  （`Cannot find module` など）が出る。

どの MIB にも定義が無い OID は対象外です。確認は抽出と同時に進めるので、時間はあまり増えません。
端末では進行状況を 1 行で表示します。

### 実行例

実機のスイッチ 2 台の walk を、上流のコミット `c9ab98c` で処理した結果です。割合は `out/mibs/` の
1,669 ファイルに対するものです（cisco-mibs 自体は `v1/` 1,142 と `v2/` 1,654 の計 2,796 ファイルですが、
`v1/` の大半は `v2/` を SMIv1 に変換したものなので、`out/mibs/` を基準にしています）。

| 機器 | walk の OID 数 | 列挙したファイル | `--exclude-dir /usr/share/snmp/mibs` 付き |
|---|---|---|---|
| Catalyst 3850（IOS-XE 03.07.04E） | 62,838 | **144**（8.6%） | **119**（7.1%） |
| Catalyst 2960-X（IOS 15.2(6)E） | 29,088 | **93**（5.6%） | **68**（4.1%） |

`/usr/share/snmp/mibs` は Ubuntu 24.04 の Net-SNMP 5.9.4 パッケージのものです。どちらも `--verify` は
成功します。3850 だけが必要とする 56 ファイルのうち 21 は、内蔵の無線コントローラ用
（AIRESPACE-\*、CISCO-LWAPP-\*）です。

## OID を定義している MIB を調べる

`lookup_mib.py` は、OID や名前を定義しているモジュールとファイルを表示します。Net-SNMP は不要です。

```sh
python3 lookup_mib.py out/mibs 1.3.6.1.4.1.9.9.13.1.4.1.3.1
python3 lookup_mib.py out/mibs ifDescr IF-MIB::ifDescr.1 SNMPv2-SMI::enterprises.9.9.13
python3 lookup_mib.py out/mibs ciscoEnvMonFanState --detail
python3 lookup_mib.py out/mibs ciscoEnvMonFanState --deps
python3 lookup_mib.py out/mibs ciscoEnvMonFanState --deps --exclude-dir /usr/share/snmp/mibs
python3 lookup_mib.py out/mibs ciscoEnvMonFanState --deps --load-order
python3 lookup_mib.py out/mibs < oids.txt
```

```
lookup_mib.py MIB_DIR [MIB_DIR ...] [QUERY ...] [--deps [--exclude-dir DIR] [--load-order] | --detail]
```

| 引数 | 意味 |
|---|---|
| `MIB_DIR` | MIB のディレクトリ。通常は `out/mibs`。先頭から続くディレクトリの引数が `MIB_DIR`、残りが検索語です |
| `QUERY` | 数値の OID、名前（`ifDescr`）、モジュール付きの名前（`IF-MIB::ifDescr`）、またはそれにインスタンスを付けたもの（`ifDescr.1`）。`QUERY` が無い時は stdin から 1 行に 1 つ読みます（各行の最初の語なので、`snmpwalk -On` の出力もそのまま使えます） |
| `--detail` | 定義（`SYNTAX`、`MAX-ACCESS`、`DESCRIPTION` など）も表示します |
| `--deps` | 結果の代わりに、名前を付けるのに必要なファイルを、import するモジュールも含めて表示します |
| `--exclude-dir DIR` | `--deps` と一緒に使い、`DIR` かその下のディレクトリにすでにあるモジュールを除きます。Net-SNMP 付属の標準 MIB などです。複数指定できます |
| `--load-order` | `--deps` と一緒に使い、名前順ではなく、各ファイルを、それが import するモジュールの後になる順で表示します |

結果は 1 件ごとにタブ区切りの 1 行です。

```
1.3.6.1.4.1.9.9.13.1.4.1.3.1	CISCO-ENVMON-MIB::ciscoEnvMonFanState.1	OBJECT-TYPE	out/mibs/CISCO-ENVMON-MIB.my
```

名前は、MIB が定義している一番深いノードで、その下の部分を後ろに付けます。複数のモジュールが定義している
名前や OID（たとえば `IF-MIB` と `RFC1213-MIB` の `ifDescr`）は、それぞれ 1 行ずつ表示します。
見つからない検索語は stderr に出し、その場合は終了ステータスが 1 になります。

### キャッシュ

`extract_mibs.py` と `lookup_mib.py` は、MIB ファイルから読んだ内容を `~/.cache/ent9-mibfix/`
（または `$XDG_CACHE_HOME/ent9-mibfix/`）に保存します。次回からは、サイズか時刻が変わったファイルだけを
読み直します。このフォルダはいつ消しても問題ありません。

## 検証結果

上流のコミット `c9ab98c` を、Net-SNMP 5.10.pre3（GitHub の開発版をビルド）と
pysmi 1.6.3 で確認しました。

| 確認内容 | 修正前（元の `v2/`） | 修正後 |
|---|---|---|
| Net-SNMP：各モジュールを単独で読み込んだ時のエラー | 135 モジュール / 1,318 行 | **0** |
| Net-SNMP：`-m ALL` で読み込んだ時のエラー | 96 行 | **0** |
| pysmi：コンパイルに失敗したモジュール | 55 | **0** |
| pysmi：モジュール名で見つからないモジュール | 25 | 1（DOCS-PNM-MIB。下記） |
| 元のラベル → OID 対応（`snmptranslate -Tz`） | 151,741 ラベル | 消えたもの・変わったもの **0**、新たに解決できたもの 1,356 |

最後の行は、修正によって既存の OID の意味が変わっていないことの確認です。
上の 2 の OLD-CISCO-\* モジュールは、この検証の後に追加したものです。Net-SNMP 5.9.4 でのみ確認しており、
各モジュールは単独でエラーなく読み込め、`-m ALL` の出力も変わりません。
同じ入力で 2 回実行すると、まったく同じ出力になります。

Net-SNMP 5.9.4（Ubuntu 24.04 のパッケージ）で `-Pu` を付けて `-m ALL` で読み込むと、
約 100 行のメッセージが残ります（修正前は 262 行）。ほとんどは AGENT-CAPABILITIES 文
（`*-CAPABILITY` モジュール）が、対象の MIB に無いオブジェクトやグループを挙げているものです。
AGENT-CAPABILITIES 文はエージェントの対応状況を記述するもので、名前 ↔ OID の変換には影響しません。
残りは MODULE-COMPLIANCE 文の誤り（CISCO-FC-FE-MIB、CISCO-SIP-UA-MIB）、
REVISION 句の日付の誤り（DOCS-CABLE-DEVICE-TRAP-MIB）、DOCS-PNM-MIB が無いことによるものです。

## 判断を含む修正

元の MIB から意図が一意に決まらず、判断を入れた修正です。`CHANGES.md` では「推定を含む」と書いています。
いずれも、監視で取得するオブジェクトの OID は変えていません。

- **名前付きビットの無い `SYNTAX BITS`** → `OCTET STRING`（CISCO-FIREPOWER-* の 3 オブジェクト）。
  BITS は通信上 OCTET STRING なので値の取得には影響しませんが、ビット名での表示はできません。
- **CISCO-ATM-PVCTRAP-EXTN-CAPABILITY**：AGENT-CAPABILITIES 文に `::=` が 12 個あったものを 1 つに整理。
- **CISCO-FC-FE-MIB**：日付の無い REVISION の説明文を、直前の説明文に結合（日付は推測していません）。
- **重複した列挙ラベル**（CISCO-LWAPP-SI-MIB の `byte(0)`〜`byte(5)` など）→ 2 つ目以降を `byte1` などに改名。
- **AGENT-CAPABILITIES 文と MODULE-IDENTITY の名前の重複**（3 モジュール）→ AGENT-CAPABILITIES 側に
  `Stmt` を付けて改名。

## 既知の制約

### DOCS-PNM-MIB（CableLabs）

`CISCO-CABLE-PNM-MIB` が 1 シンボル（`docsPnmCmtsUtscCfgIndex`）を import しています。
CableLabs が配布している MIB で、Net-SNMP にも LibreNMS にもありません。Net-SNMP と pysmi は、
これが無くても `CISCO-CABLE-PNM-MIB` を読み込めますが、厳密なツールではエラーになります。
必要なら CableLabs から入手し、そのディレクトリを `EXTRA_MIB_DIR` に指定してください。

### Cisco の MIB 同士の OID 重複

異なるモジュールが同じ OID を使っているものがあります。正しい番号は Cisco にしか分からないため、
変更していません。**両方のモジュールを同時に読み込んだ時だけ**、OID → 名前の変換でもう一方の名前が
出ることがあります。

- **仮番号のまま公開されている MIB**（`ciscoMgmt.9999` / `.99999`、`ciscoExperiment.999`、
  `ciscoAgentCapability.999` / `.9999` / `.99999`）：
  CISCO-AAL5-EXT-MIB、CISCO-ATM-CONN-INFO-MIB、CISCO-CPRI-MIB、CISCO-DS0-CROSS-CONNECT-MIB、
  CISCO-FC-TUNNEL-MIB、CISCO-MPOA-EXT-MIB、CISCO-WAN-ATM-CUG-MIB、CISCO-IETF-PPVPN-MPLS-VPN-MIB、
  CISCO-IETF-VRRP-MIB、CISCO-IF-MONITOR-NOTIF-MIB、CISCO-CABLE-DSG-IF-MIB と、多数の *-CAPABILITY
- **番号そのものの衝突**
  - `ciscoMgmt.115`：CISCO-CABLE-PNM-MIB と CISCO-CASA-FA-MIB
  - `ciscoMgmt.510`：CISCO-ERM-MIB と CISCO-VOICE-LMR-MIB
  - `ciscoAgentCapability.102`：CISCO-RFC1406-CAPABILITY と CISCO-RFC1407-CAPABILITY
  - `axisDiagnostics.2`：BASIS-RAS-DISK-MIB と CISCO-MGX82XX-DSX3-BERT-MIB
- **標準 MIB 側の別名（実害なし）**：`ccitt.0`、`iso.3`、`ieee.2`、`rmonConformance.8`、`intSrv.4` など。
  `transmission.32` は、`v1/` から追加した RFC1315-MIB（旧版）と FRAME-RELAY-DTE-MIB が、
  同じ OID を別名で定義しているものです。

`v1/` から追加した AWCVX-MIB（Aironet）は、SNMP-COMMUNITY-MIB と同名の `snmpTrapCommunity` という
オブジェクトを定義しています。名前で指定する時は、`SNMP-COMMUNITY-MIB::snmpTrapCommunity` のように
モジュール名を付けてください。

### 他のバージョンの上流

修正の多くは汎用的なものですが、特定の MIB の特定の箇所を狙った修正もあります。Cisco がリポジトリを
更新すると、それらは該当箇所が見つからなくなることがあります。その場合は `CHANGES.md` に
「適用されなかった修正」として記録されますが、新しく入った問題は自動では直りません。
実行するたびに `CHANGES.md` を確認してください。

`smiscan.py` は完全な ASN.1 パーサではありません。モジュール名、import、定義、モジュールが使っている
シンボルを見つけるのに必要な分だけを読み取ります。

## Cisco への報告

cisco-mibs の CONTRIBUTING によると、構文の誤りや import 漏れは、`smilint` の出力を付けて
Cisco TAC に報告すれば、不具合として登録されます。`CHANGES.md` は報告の材料に使えます。

## ライセンス

このリポジトリのスクリプトは [Apache License 2.0](LICENSE) で公開しています。
[NOTICE](NOTICE) も参照してください。

スクリプトが読み書きする MIB は Cisco（標準 MIB はそれぞれの作成者）のもので、このライセンスの
対象ではありません。このリポジトリは、それらを含まず、再配布もしません。

## Cisco へ（と、皆さんへ）

ent9-mibfix があるのは、cisco/cisco-mibs の MIB の多くが、公開されたままではきちんと読み込めないからです。
それでも簡単には直せない事情も分かります。今の MIB を前提に動いているシステムがあり、公開済みの MIB を
変えるには必ず代償が伴います。そこでこのプロジェクトは、利用者の側で直すことにしました。
いつかこのプロジェクトが不要になれば、それが一番です。

ent9-mibfix を使っている皆さんへ：役に立ったら、アイスクリームを奢ってください。🍦

そして一番得をしているはずの Cisco には、It's-It（1928 年からサンフランシスコで愛されているアイスクリームサンド）を
お願いします。

*これはお願いであって、ライセンスの条件ではありません。スクリプトは Apache-2.0 で、追加の条件はありません。*
