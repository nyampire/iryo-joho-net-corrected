#!/usr/bin/env python3
"""訂正済みデータセットの自己テストに使う、小さな元データと生成物を組み立てる。

selftest_corrected.py と selftest_validate_corrected.py が共有する。
元データのファイル名は実物と同じ形にし、build_opening_hours.SECTORS の
パターンで見つかるようにする。列は処理が読むものだけに絞る。

病院は施設票と診療科の票の2ファイル、薬局は1ファイル。
2つの持ち方の両方を通すために、この2業態を選んでいる。
"""

import os

LAT, LON = "所在地座標（緯度）", "所在地座標（経度）"
DAYS = "月火水木金土日"
DAYS_PH = DAYS + "祝"


def write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        # 元データの形を写す: 見出しは全列引用符付き、データ行は緯度経度の2列だけ引用符なし
        bare = {header.index(LAT), header.index(LON)} if LAT in header else set()

        def record(fields, bare_cols):
            return ",".join(v if i in bare_cols else '"' + v.replace('"', '""') + '"'
                            for i, v in enumerate(fields))

        f.write(record(header, set()) + "\r\n")
        for row in rows:
            f.write(record(row, bare) + "\r\n")


def flags(open_days):
    return ["1" if d in open_days else "0" for d in DAYS]


def hospital(data_dir):
    header = (["ID", "正式名称", "都道府県コード", LAT, LON, "案内用ホームページアドレス"]
              + [f"毎週決まった曜日に休診（{d}）" for d in DAYS]
              + ["祝日に休診", "その他の休診日（gw、お盆等）"])
    rows = [
        ["H001", "病院1", "01", "43.055405", "141.333497", "http//www.example.jp",
         *flags("月火水木金"), "0", "8/14-5/16"],
        ["H002", "病院2", "01", "0.0", "0.0", "example.jp",
         *flags("月火水木金土"), "0", ""],
        ["H003", "病院3", "01", "0.0", "0.0", "https://www.bing.com/ck/a?u=x",
         *flags(""), "0", ""],
        ["H004", "病院4", "01", "43.0", "141.0", "http:/www.example.jp",
         *flags(""), "0", ""],
        ["H005", "病院5", "01", "34.0", "135.0", "", *flags(""), "0", ""],
        ["H006", "病院6", "01", "43.2", "141.5", "", *flags(""), "0", ""],
    ]
    write(os.path.join(data_dir, "01-1_hospital_facility_info_20990101.csv"), header, rows)

    hours_header = ["ID", "診療科目コード", "診療科目名", "診療時間帯"]
    for d in DAYS_PH:
        hours_header += [f"{d}_診療開始時間", f"{d}_診療終了時間",
                         f"{d}_外来受付開始時間", f"{d}_外来受付終了時間"]

    def hours(fid, code, name, slot, cells):
        """cells は {列名: 値}。書かなかった列は空欄。"""
        row = [fid, code, name, slot] + [""] * (len(hours_header) - 4)
        for col, v in cells.items():
            row[hours_header.index(col)] = v
        return row

    weekday = {}
    for d in "月火水木金":
        weekday[f"{d}_診療開始時間"] = "09:00"
        weekday[f"{d}_診療終了時間"] = "17:00"
    morning = {}
    for d in "月火水木金":
        morning[f"{d}_診療開始時間"] = "09:00"
        morning[f"{d}_診療終了時間"] = "12:00"
    hours_rows = [
        # 土曜は施設票で休診だが、平日と同じ時刻が入っている
        hours("H001", "01001", "内科", "1",
              {**weekday, "土_診療開始時間": "09:00", "土_診療終了時間": "17:00",
               "月_外来受付開始時間": "08:45", "月_外来受付終了時間": "11:00"}),
        hours("H001", "01001", "内科", "2",
              {"火_診療開始時間": "17:00", "火_診療終了時間": "17:00"}),
        hours("H001", "13001", "耳鼻いんこう科", "1",
              {"火_診療開始時間": "00:45", "火_診療終了時間": "17:15",
               "水_診療開始時間": "00:00", "水_診療終了時間": "23:59",
               "木_外来受付開始時間": "08:30", "木_外来受付終了時間": "08:30"}),
        # 救急科は日曜（施設票で休診）に時刻があっても矛盾として数えない
        hours("H001", "09010", "救急科", "1",
              {"日_診療開始時間": "08:00", "日_診療終了時間": "20:00"}),
        hours("H002", "01001", "内科", "1",
              {**morning,
               "月_外来受付開始時間": "09:00", "月_外来受付終了時間": "23:30",
               "火_外来受付開始時間": "15:30", "火_外来受付終了時間": "15:00"}),
    ]
    write(os.path.join(data_dir, "01-2_hospital_speciality_hours_20990101.csv"),
          hours_header, hours_rows)


def pharmacy(data_dir):
    header = (["ID", "名称", "都道府県コード", LAT, LON, "薬局のホームページアドレス"]
              + [f"営業日（{d}）" for d in DAYS]
              + ["営業日（祝）", "その他の閉店日（gw、お盆等）"])
    for d in DAYS_PH:
        for s in range(1, 5):
            header += [f"{d}_開店時間帯{s}_開始時間", f"{d}_開店時間帯{s}_終了時間"]
    row = ["P001", "薬局1", "01", "43.0", "141.3", "https://example.jp/",
           *flags("月火水木金"), "0", ""] + [""] * (len(header) - 15)
    for d in "月火水木金土":
        row[header.index(f"{d}_開店時間帯1_開始時間")] = "09:00"
        row[header.index(f"{d}_開店時間帯1_終了時間")] = "18:00"
    row[header.index("月_開店時間帯2_開始時間")] = "12:00"
    row[header.index("月_開店時間帯2_終了時間")] = "12:00"
    write(os.path.join(data_dir, "05_pharmacy_20990101.csv"), header, [row])


def geocoded(build_dir):
    header = ["ID", "元_緯度", "元_経度", "座標の出典", "座標の理由",
              "住所_lat", "住所_lon", "住所_位置レベル", "元_所在地"]
    rows = [
        ["H001", "43.055405", "141.333497", "原データ", "", "43.056339", "141.33299", "3", ""],
        ["H002", "0.0", "0.0", "ジオコーディング", "",
         "43.069891362", "141.334289858", "8", ""],
        ["H003", "0.0", "0.0", "なし", "", "", "", "", ""],
        ["H004", "43.0", "141.0", "なし",
         "元データの座標 43.0, 141.0 を別の市区町村の施設と共有しているため使わない",
         "43.06", "141.35", "3", ""],
        ["H005", "34.0", "135.0", "ジオコーディング",
         "元データの座標 34.0, 135.0 が北海道ではなく大阪府と兵庫県の範囲にあるため、ジオコーダ座標を採用",
         "43.3", "141.6", "3", ""],
        ["H006", "43.2", "141.5", "ジオコーディング",
         "元データの座標 43.2, 141.5 がジオコーダ座標から1,523m離れているため、ジオコーダ座標を採用",
         "43.21", "141.51", "8", ""],
    ]
    write(os.path.join(build_dir, "hospital_geocoded.csv"), header, rows)
    write(os.path.join(build_dir, "pharmacy_geocoded.csv"), header,
          [["P001", "43.0", "141.3", "原データ", "", "", "", "", ""]])


def make_fixture(root):
    """root の下に入力一式を作り、各ディレクトリのパスを返す。"""
    paths = {
        "data_dir": os.path.join(root, "data"),
        "build_dir": os.path.join(root, "build"),
        "chiban": os.path.join(root, "build", "chiban_points.csv"),
        "out_dir": os.path.join(root, "corrected"),
    }
    hospital(paths["data_dir"])
    pharmacy(paths["data_dir"])
    geocoded(paths["build_dir"])
    write(paths["chiban"], ["業態", "ID", "lat", "lon"],
          [["hospital", "H003", "43.1", "141.4"], ["hospital", "H005", "43.4", "141.7"]])
    return paths
