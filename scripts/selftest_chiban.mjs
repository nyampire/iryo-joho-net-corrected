#!/usr/bin/env node
/**
 * geocode_chiban.mjs の逆テスト。
 *
 * 固定しているのは2つ。
 *   needsChiban     どの行に地番の点を問い合わせるか
 *   pickChibanPoint NJA の結果から地番の点を採るか
 *
 * pickChibanPoint の入力は、2026-10-02 に地番方式の住所を NJA に直接通した結果の形。
 * 照合結果の level が 8 でも、地番の位置データが無ければ point.level は 2 や 3 になる。
 * level だけを見ると、町字や市区町村の代表点を地番の点として採ってしまう。
 */
import { needsChiban, pickChibanPoint } from "./geocode_chiban.mjs";

const cases = [
  ["元データの座標を使う行は問い合わせない",
    needsChiban({ "座標の出典": "原データ", "住所_位置レベル": "" }), false],
  ["住居表示の点で置き換えた行は問い合わせない",
    needsChiban({ "座標の出典": "ジオコーディング", "住所_位置レベル": "8" }), false],
  ["座標が無く住所の点も無い行は問い合わせる",
    needsChiban({ "座標の出典": "なし", "住所_位置レベル": "" }), true],
  ["座標が無く町字の代表点しか無い行は問い合わせる",
    needsChiban({ "座標の出典": "なし", "住所_位置レベル": "3" }), true],
  ["県の外を指す座標を町字の代表点で置き換えた行は問い合わせる",
    needsChiban({ "座標の出典": "ジオコーディング", "住所_位置レベル": "3" }), true],
  ["地番の位置があれば採る",
    JSON.stringify(pickChibanPoint({
      level: 8,
      point: { lat: 35.95826785, lng: 140.526370123, level: 8 },
      metadata: { chiban: { prc_num1: "733", point: [140.526370123, 35.95826785] } },
    })),
    JSON.stringify({ lat: "35.95826785", lon: "140.526370123" })],
  ["照合結果の level が8でも、点の level が3なら採らない",
    pickChibanPoint({
      level: 8,
      point: { lat: 34.820455, lng: 132.519902, level: 3 },
      metadata: { chiban: { prc_num1: "2180", prc_num2: "2" } },
    }), null],
  ["照合結果の level が8でも、点の level が2なら採らない",
    pickChibanPoint({
      level: 8,
      point: { lat: 34.954809, lng: 137.172999, level: 2 },
      metadata: { chiban: { prc_num1: "21" } },
    }), null],
  ["住居表示の点は採らない",
    pickChibanPoint({
      level: 8,
      point: { lat: 43.0, lng: 141.3, level: 8 },
      metadata: { rsdt: { blk_num: "1", rsdt_num: "1" } },
    }), null],
  ["結果が無ければ採らない", pickChibanPoint(null), null],
];

let failed = 0;
console.log("=== geocode_chiban.mjs 逆テスト ===\n");
for (const [name, got, want] of cases) {
  const ok = got === want;
  if (!ok) failed++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) {
    console.log(`        実際: ${got}`);
    console.log(`        期待: ${want}`);
  }
}
console.log(`\n  ${cases.length - failed}/${cases.length} 件`);
process.exit(failed ? 1 : 0);
