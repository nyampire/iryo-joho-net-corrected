#!/usr/bin/env python3
"""訂正済みデータセットから1県分を抜き出し、samples/ に置く。

入力:
  output/corrected/<元データと同じファイル名>   8ファイル

出力:
  samples/<県コード>_<県名>/<同じファイル名>

output/ は .gitignore で追跡していない。全件は数百MBあるため。
スクリプトを回せない人も中身を確かめられるよう、1県分だけをリポジトリに置く。
GitHub の Web UI は .csv を表として描く。

施設票（助産所と薬局では唯一の票）は 都道府県コード で絞り、診療科の票は
絞った施設の ID を持つ行だけを残す。行は出力の文字列をそのまま写すので、
引用符の付け方や改行まで出力と同じになる。

既定は高知県（39）。jp-healthcare-osm の samples/ と同じ県にそろえ、
2つのリポジトリの出力を同じ施設で見比べられるようにする。

出力を変えたら、そのコミットで一緒に流し直す。

使い方:
  python3 scripts/build_samples.py [--pref 39] [--src output/corrected]
"""

import argparse
import csv
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "vendor", "jp-healthcare-osm", "scripts"))
from prefectures import PREF  # noqa: E402

SAMPLES_DIR = "samples"
DEFAULT_PREF = "39"
# 元データのファイル名。施設票は NN-1_ か NN_、診療科の票は NN-2_
RE_FACILITY = re.compile(r"^0\d(-1)?_[a-z_]+_\d{8}\.csv$")
RE_HOURS = re.compile(r"^0\d-2_[a-z_]+_\d{8}\.csv$")
PREF_COL = "都道府県コード"


def records(path):
    """BOM を除いた見出しと、1件ずつのレコード文字列を返す。

    値の中に改行を含むレコードがあるので、引用符の数が偶数になるまで行をつなぐ。
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = f.read().split("\r\n")
    if lines and lines[-1] == "":
        lines.pop()
    out = []
    buf = None
    for line in lines:
        buf = line if buf is None else buf + "\r\n" + line
        if buf.count('"') % 2 == 0:
            out.append(buf)
            buf = None
    if buf is not None:
        sys.exit(f"引用符が閉じていません: {path}")
    return out[0], out[1:]


def fields(record):
    return next(csv.reader(io.StringIO(record)))


def write(path, header, recs):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(header + "\r\n")
        for r in recs:
            f.write(r + "\r\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pref", default=DEFAULT_PREF)
    p.add_argument("--src", default=os.path.join("output", "corrected"))
    args = p.parse_args()

    code = args.pref.zfill(2)
    if code not in PREF:
        sys.exit(f"県コードが不正です: {args.pref}")
    dest = os.path.join(SAMPLES_DIR, f"{code}_{PREF[code]}")

    names = sorted(os.listdir(args.src)) if os.path.isdir(args.src) else []
    facility = [n for n in names if RE_FACILITY.match(n)]
    hours = [n for n in names if RE_HOURS.match(n)]
    # 途中で気づくと、古いサンプルと新しいサンプルが混ざる
    if len(facility) != 5 or len(hours) != 3:
        sys.exit(f"{args.src} に8ファイルが揃っていません。先に npm run correct を実行してください")

    os.makedirs(dest, exist_ok=True)
    print(f"対象県 : {code} {PREF[code]}")
    # 業態ごとの施設 ID。ファイル名の先頭2文字（01 が病院）で施設票と診療科の票を対にする
    ids = {}
    for name in facility:
        header, recs = records(os.path.join(args.src, name))
        i = fields(header).index(PREF_COL)
        kept = [r for r in recs if fields(r)[i] == code]
        ids[name[:2]] = {fields(r)[0] for r in kept}
        write(os.path.join(dest, name), header, kept)
        print(f"  {name:<45} {len(kept):>6,} 行")
    for name in hours:
        header, recs = records(os.path.join(args.src, name))
        kept = [r for r in recs if fields(r)[0] in ids[name[:2]]]
        write(os.path.join(dest, name), header, kept)
        print(f"  {name:<45} {len(kept):>6,} 行")


if __name__ == "__main__":
    main()
