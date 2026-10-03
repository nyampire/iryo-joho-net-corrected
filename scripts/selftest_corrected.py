#!/usr/bin/env python3
"""build_corrected.py の自己テスト。

corrected_fixtures.py が組み立てた小さな元データに通し、出力の各行を照合する。
規則そのものは selftest_corrected_rules.py が固定しているので、ここで見るのは
規則をどの列に当てたか、注記をどの行に書いたか、行と列の並びを保ったか。

施設票と診療科の票の両方に書く注記（曜日フラグと時刻の矛盾）はここでしか確かめられない。
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_corrected import correct_sector  # noqa: E402
from corrected_fixtures import LAT, LON, make_fixture  # noqa: E402


def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        header = next(r)
        return header, [dict(zip(header, row)) for row in r]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        p = make_fixture(tmp)
        for sector in ("hospital", "pharmacy"):
            correct_sector(sector, p["data_dir"], p["build_dir"], p["chiban"], p["out_dir"])
        out = p["out_dir"]
        fh, fac = read(os.path.join(out, "01-1_hospital_facility_info_20990101.csv"))
        hh, hrs = read(os.path.join(out, "01-2_hospital_speciality_hours_20990101.csv"))
        ph, pha = read(os.path.join(out, "05_pharmacy_20990101.csv"))
        with open(os.path.join(out, "01-1_hospital_facility_info_20990101.csv"), "rb") as f:
            head_bytes = f.read(7)
        with open(os.path.join(out, "01-1_hospital_facility_info_20990101.csv"),
                  encoding="utf-8-sig", newline="") as f:
            text = f.read()
        lines = {ln.split(",", 1)[0].strip('"'): ln for ln in text.split("\r\n")}
        rh, _ = read(os.path.join(p["data_dir"], "01-1_hospital_facility_info_20990101.csv"))
        rhh, _ = read(os.path.join(p["data_dir"], "01-2_hospital_speciality_hours_20990101.csv"))

    f = {r["ID"]: r for r in fac}
    cases = [
        # 形
        ("施設票は元の列の後に 注記 と 座標の出典 を足す", fh, rh + ["注記", "座標の出典"]),
        ("診療科の票は元の列の後に 注記 だけを足す", hh, rhh + ["注記"]),
        ("施設票の行の順序を保つ", [r["ID"] for r in fac],
         ["H001", "H002", "H003", "H004", "H005", "H006"]),
        ("診療科の票の行数を保つ", len(hrs), 5),
        ("BOM と引用符を元データにそろえる", head_bytes, '﻿"ID"'.encode("utf-8")),

        # 緯度経度の2列だけ引用符を付けない（元データの書き方）
        ("緯度経度は引用符なしで書く", ',43.055405,141.333497,' in lines["H001"], True),
        ("座標を空欄にした行は緯度経度の位置が ,, になる",
         '"病院4","01",,,' in lines["H004"], True),
        ("見出しは全列引用符付き", lines["ID"].startswith('"ID","正式名称"'), True),

        # 座標
        ("元データの座標は残す", (f["H001"][LAT], f["H001"]["座標の出典"]),
         ("43.055405", "原データ")),
        ("0,0 は住居表示の点に置き換える", (f["H002"][LAT], f["H002"][LON], f["H002"]["座標の出典"]),
         ("43.069891362", "141.334289858", "住居表示")),
        ("住居表示の点が無ければ地番の点に置き換える",
         (f["H003"][LAT], f["H003"][LON], f["H003"]["座標の出典"]), ("43.1", "141.4", "地番")),
        ("位置レベル8の点が無ければ空欄にする",
         (f["H004"][LAT], f["H004"][LON], f["H004"]["座標の出典"]), ("", "", "")),
        ("町字の代表点で置き換えた県外の座標は地番の点にする",
         (f["H005"][LAT], f["H005"]["座標の出典"]), ("43.4", "地番")),

        # 施設票の注記
        ("施設票に矛盾と休診日と URL の注記を書く", f["H001"]["注記"],
         "疑い: 土 曜日フラグは休みだが時刻が入っている"
         " / 疑い: その他の休診日（gw、お盆等） 8/14-5/16（範囲が31日を超える。終点の打ち間違いの疑い）"
         " / 書き換えた: ホームページアドレス http//www.example.jp → http://www.example.jp（コロンの脱字）"),
        ("URL を直す", f["H001"]["案内用ホームページアドレス"], "http://www.example.jp"),
        ("救急科の日曜の時刻は矛盾として数えない", "日 " in f["H001"]["注記"], False),
        ("時刻が無い営業日は施設票にだけ書く", f["H002"]["注記"],
         "書き換えた: 緯度経度 0.0, 0.0 → 住居表示の点（欠損を示す値）"
         " / 疑い: 土 曜日フラグは営業日だが時刻が無い"
         " / 疑い: ホームページアドレス example.jp（スキームが無い）"),
        ("転送 URL を空欄にする", f["H003"]["案内用ホームページアドレス"], ""),

        # 診療科の票
        ("休診日の時刻は、その時刻を持つ診療科の行にも書く", hrs[0]["注記"],
         "疑い: 土 施設票の曜日フラグは休みだが時刻が入っている"),
        ("開始と終了が同じ区間を空欄にする",
         (hrs[1]["火_診療開始時間"], hrs[1]["火_診療終了時間"], hrs[1]["注記"]),
         ("", "", "空欄にした: 火_診療 17:00-17:00（開始と終了が同じ）")),
        ("外来受付の系列にも同じ規則を当てる",
         (hrs[2]["木_外来受付開始時間"], hrs[2]["注記"]),
         ("", "疑い: 火_診療 00:45-17:15（開始が 06:00 より前）"
              " / 空欄にした: 木_外来受付 08:30-08:30（開始と終了が同じ）")),
        ("疑いの区間は値を残す", hrs[2]["火_診療開始時間"], "00:45"),
        ("00:00-23:59 は残して注記しない", hrs[2]["水_診療終了時間"], "23:59"),
        ("救急科の行には注記を書かない", hrs[3]["注記"], ""),
        ("受付の系列の疑いを書く", hrs[4]["注記"],
         "疑い: 月_外来受付 09:00-23:30（終了が 23:00 より後）"
         " / 疑い: 火_外来受付 15:30-15:00（日跨ぎとしても 18時間を超える）"),

        # 薬局（フラグと時刻が同じ行にある）
        ("薬局は時刻と矛盾の注記を同じ行に書く", pha[0]["注記"],
         "空欄にした: 月_開店時間帯2 12:00-12:00（開始と終了が同じ）"
         " / 疑い: 土 曜日フラグは休みだが時刻が入っている"),
        ("薬局の座標の出典", pha[0]["座標の出典"], "原データ"),
        ("薬局の列", ph[-2:], ["注記", "座標の出典"]),
    ]

    failed = 0
    print("=== build_corrected.py 自己テスト ===\n")
    for name, got, want in cases:
        ok = got == want
        if not ok:
            failed += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        実際: {got}")
            print(f"        期待: {want}")
    print(f"\n  {len(cases) - failed}/{len(cases)} 件")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
