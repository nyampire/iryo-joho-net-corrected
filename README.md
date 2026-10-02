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

## ライセンスと出典

スクリプトなど、このリポジトリで作成した部分は MIT ライセンスです。
全文は [LICENSE](LICENSE) にあります。
