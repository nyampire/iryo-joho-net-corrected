# iryo-joho-net-corrected

厚生労働省「医療情報ネット」のオープンデータを、元の列のまま、誤りと確定できる値だけを直したデータセットにする作業リポジトリです。

OpenStreetMap 向けのタグへの変換は [jp-healthcare-osm](https://github.com/nyampire/jp-healthcare-osm) が扱います。
このリポジトリは jp-healthcare-osm を submodule として取り込み、座標の判定と時刻の判定のコードをそのまま使います。

## 元データ

2026年6月1日時点 医療情報ネットのオープンデータ（厚生労働省）を使います。

配布元は https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/newpage_43373.html です。
8ファイルをリポジトリ直下に置いてください。
元データと生成物はこのリポジトリに含めていません。

## 使い方

```bash
git submodule update --init --recursive
npm install
export NJA_API_BASE=/path/to/japanese-addresses-v2/out/api/ja
npm run all
```

住所データの取得先 `NJA_API_BASE` の設定は必須です。
手元に構築した `japanese-addresses-v2` を指してください。
構築の手順は `vendor/jp-healthcare-osm/vendor/nja-osm-tags/docs/local-mirror.md` にあります。

## 出力

`output/corrected/` に、元データと同じファイル名で8ファイルを書きます。
列と行の並びは元データと同じで、末尾に `注記` 列を足します。
緯度経度を持つファイルにはさらに `座標の出典` 列を足します。
施設票と診療科の票は、元データと同じく `ID` 列で紐づきます。

直すのは次の値だけです。

| 列 | 直す値 | 扱い |
|---|---|---|
| 緯度、経度 | `0.0, 0.0`、穴埋めの座標、住所の県の外を指す座標、住所の点から1km以上離れた座標 | 住所から得た位置レベル8の点に置き換える。無ければ空欄 |
| 時刻 | 開始と終了が同じ区間 | 空欄にする |
| ホームページアドレス | コロンの脱字 | 補う |
| ホームページアドレス | 検索エンジンの転送 URL | 空欄にする |

06:00より前の開始、23:00より後の終了、曜日フラグと時刻の矛盾、31日を超える休診日の範囲、
スキームの無い URL は、元の値を残して `注記` に書きます。
直した値も、元の値を `注記` に残します。

| 座標の出典 | 件数 |
|---|---:|
| 原データ | 189,395 |
| 住居表示 | 7,278 |
| 地番 | 2,873 |
| 空欄 | 6,497 |

`座標の出典` が `地番` の座標は、地番の位置データから得たものです。
このデータには登記所備付地図データ利用規約が適用され、OpenStreetMap には入れられません。
jp-healthcare-osm がこの座標を使わないのはそのためです。

途中の生成物は `output/build/` に置きます。

| ファイル | 内容 |
|---|---|
| `<業態>_geocoded.csv` | jp-healthcare-osm の座標の判定の結果 |
| `chiban_points.csv` | 地番の点（業態、ID、緯度、経度） |

## ライセンスと出典

スクリプトなど、このリポジトリで作成した部分は MIT ライセンスです。
全文は [LICENSE](LICENSE) にあります。

変換対象となる厚生労働省の元データには公共データ利用規約（第1.0版）(PDL1.0) が適用されています。
`座標の出典` が `住居表示` の座標は、アドレス・ベース・レジストリから得ており、同じく公共データ利用規約（第1.0版）が適用されます。
`座標の出典` が `地番` の座標は、アドレス・ベース・レジストリの地番マスター位置参照から得ており、
[登記所備付地図データ利用規約](https://www.digital.go.jp/policies/base_registry_address_tos) が適用されます。

### 出典明示

`output/corrected/` のデータを再配布する際には、以下の文言を含めてください。
どちらの規約も、出典とは別に、加工したことと加工した主体を書くよう求めています。
加工した主体として、再配布する方の名称を書き添えてください。

```
「医療情報ネットのオープンデータ」（厚生労働省）（https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/newpage_43373.html）を加工して作成
「アドレス・ベース・レジストリ」（デジタル庁）（https://www.digital.go.jp/policies/base_registry_address_tos）を加工して作成
```
