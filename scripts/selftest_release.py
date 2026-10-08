#!/usr/bin/env python3
"""build_release.py の自己テスト。

corrected_fixtures.py の小さな元データを build_corrected.py に通し、その出力を
build_release.py で ZIP にして中身を照合する。fixture の施設はすべて北海道（01）。

固定しているのは次の点。
  ZIP の名前と、中のフォルダとファイルの並び
  CSV は出力の行をそのまま写し、BOM と CRLF を保つ
  GeoJSON は緯度経度のある施設だけを点にし、属性は CSV と同じ文字列のまま
  README.txt に README.md の出典明示が入る
  同じ入力から同じバイト列の ZIP ができる
"""

import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_corrected import correct_sector  # noqa: E402
from build_release import build  # noqa: E402
from corrected_fixtures import LAT, LON, make_fixture  # noqa: E402

FAC = "01-1_hospital_facility_info_20990101.csv"
HRS = "01-2_hospital_speciality_hours_20990101.csv"
README = """# 見出し

### 出典明示

本文。

```
「データ1」（省）（https://example.jp/1）を加工して作成
「データ2」（庁）（https://example.jp/2）を加工して作成
```
"""


def main():
    with tempfile.TemporaryDirectory() as tmp:
        p = make_fixture(tmp)
        for sector in ("hospital", "pharmacy"):
            correct_sector(sector, p["data_dir"], p["build_dir"], p["chiban"], p["out_dir"])
        # build_release は8ファイルを求めるので、fixture に無い業態は見出しだけの空のファイルを置く
        for name in ("02-1_clinic_facility_info_20990101.csv",
                     "02-2_clinic_speciality_hours_20990101.csv",
                     "03-1_dental_facility_info_20990101.csv",
                     "03-2_dental_speciality_hours_20990101.csv",
                     "04_maternity_home_20990101.csv"):
            src = FAC if "-1_" in name or name.startswith("04") else HRS
            with open(os.path.join(p["out_dir"], src), encoding="utf-8-sig", newline="") as f:
                header = f.read().split("\r\n")[0]
            with open(os.path.join(p["out_dir"], name), "w", encoding="utf-8-sig", newline="") as f:
                f.write(header + "\r\n")
        readme = os.path.join(tmp, "README.md")
        with open(readme, "w", encoding="utf-8") as f:
            f.write(README)

        out1, out2 = os.path.join(tmp, "r1"), os.path.join(tmp, "r2")
        result = build(p["out_dir"], out1, readme)
        build(p["out_dir"], out2, readme)
        path = result["01"][0]
        name = os.path.basename(path)
        with open(path, "rb") as f1, open(os.path.join(out2, name), "rb") as f2:
            same_bytes = f1.read() == f2.read()
        with zipfile.ZipFile(path) as z:
            listing = z.namelist()
            fac_csv = z.read(f"01_北海道/{FAC}")
            hrs_csv = z.read(f"01_北海道/{HRS}").decode("utf-8-sig")
            geo = json.loads(z.read(f"01_北海道/{FAC[:-4]}.geojson"))
            text = z.read("01_北海道/README.txt").decode("utf-8")
        with open(os.path.join(p["out_dir"], FAC), "rb") as f:
            out_fac = f.read()
        with open(os.path.join(p["out_dir"], HRS), encoding="utf-8-sig", newline="") as f:
            out_hrs = f.read()
        with zipfile.ZipFile(result["13"][0]) as z:
            tokyo_rows = z.read(f"13_東京都/{FAC}").decode("utf-8-sig").count("\r\n")

    feats = {ft["properties"]["ID"]: ft for ft in geo["features"]}
    cases = [
        ("47個の ZIP を作る", len(result), 47),
        ("ZIP の名前は元データの日付と県コード", name, "iryo-joho-net-corrected_20990101_01.zip"),
        ("県名のフォルダに CSV、GeoJSON、README を入れる", listing[:2] + listing[-1:],
         ["01_北海道/01-1_hospital_facility_info_20990101.csv",
          "01_北海道/01-2_hospital_speciality_hours_20990101.csv",
          "01_北海道/README.txt"]),
        ("CSV 8個、GeoJSON 5個、README 1個", len(listing), 14),
        ("施設票の CSV は出力とバイト列ごと同じ", fac_csv, out_fac),
        ("診療科の票は北海道の施設の行をすべて写す", hrs_csv, out_hrs),
        ("施設の無い県は見出しだけ", tokyo_rows, 1),
        ("緯度経度のある施設だけを点にする", sorted(feats),
         ["H001", "H002", "H003", "H005", "H006"]),
        ("座標は経度、緯度の順の数値", feats["H001"]["geometry"]["coordinates"],
         [141.333497, 43.055405]),
        ("属性は CSV の文字列のまま", feats["H001"]["properties"][LAT], "43.055405"),
        ("属性に注記と座標の出典を含む", (feats["H002"]["properties"]["座標の出典"],
                                     feats["H002"]["properties"]["注記"].startswith("書き換えた: 緯度経度 0.0, 0.0")),
         ("住居表示", True)),
        ("README.txt に出典明示を入れる",
         "「データ1」（省）（https://example.jp/1）を加工して作成\n"
         "「データ2」（庁）（https://example.jp/2）を加工して作成" in text, True),
        ("README.txt に元データの時点を書く", "元データの時点: 2099年1月1日" in text, True),
        ("同じ入力から同じバイト列の ZIP ができる", same_bytes, True),
        ("経度の列名を使っている", LON in feats["H001"]["properties"], True),
    ]

    failed = 0
    print("=== build_release.py 自己テスト ===\n")
    for label, got, want in cases:
        ok = got == want
        if not ok:
            failed += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            print(f"        実際: {str(got)[:300]}")
            print(f"        期待: {str(want)[:300]}")
    print(f"\n  {len(cases) - failed}/{len(cases)} 件")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
