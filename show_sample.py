"""
讀取 check_serpapi.py 存下來的 serpapi_sample.json，
整理出我需要知道的資訊。

這支程式「不會連網」，所以不會消耗任何 SerpApi 額度，可以放心重複執行。

執行方式：
    python show_sample.py            讀 check_serpapi.py 存下的範例
    python show_sample.py --cache    讀你最近一次真實搜尋的結果
"""

import json
from collections import Counter
from pathlib import Path

import sys

BASE = Path(__file__).parent
SAMPLE = BASE / "serpapi_sample.json"
CACHE = BASE / "cache"

if "--cache" in sys.argv:
    files = sorted(CACHE.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit("cache/ 裡沒有東西，請先在網頁上搜尋一次。")
    source = files[0]
    print(f"讀取最近一次搜尋：{source.name}")
else:
    source = SAMPLE
    if not source.exists():
        raise SystemExit(
            "找不到 serpapi_sample.json。\n"
            "要看最近一次真實搜尋的話，請執行：python show_sample.py --cache")

data = json.loads(source.read_text(encoding="utf-8"))
params = data.get("search_parameters") or {}
if params:
    print(f"查詢條件：{params.get('q')} / "
          f"{params.get('check_in_date')} ~ {params.get('check_out_date')}")
properties = data.get("properties", [])

print("=" * 60)
print(f"總共 {len(properties)} 筆住宿")

# 住宿型態分布：確認 type 欄位能不能用來過濾「只要飯店」
print("\n--- type 欄位的值分布 ---")
for value, count in Counter(p.get("type", "(無)") for p in properties).most_common():
    print(f"  {value:<20} {count} 筆")

# 這是重點：把所有飯店出現過的設施字串收集起來，看看實際的寫法
print("\n--- 所有出現過的 amenities 字串（出現次數由多到少）---")
amenity_counter = Counter()
for p in properties:
    for a in p.get("amenities", []) or []:
        amenity_counter[a] += 1
if amenity_counter:
    for value, count in amenity_counter.most_common():
        print(f"  {count:>3} 次  {value}")
else:
    print("  （沒有任何 amenities 資料）")

# 有些飯店會明確列出「沒有」的設施
print("\n--- 所有出現過的 excluded_amenities 字串 ---")
excluded_counter = Counter()
for p in properties:
    for a in p.get("excluded_amenities", []) or []:
        excluded_counter[a] += 1
if excluded_counter:
    for value, count in excluded_counter.most_common():
        print(f"  {count:>3} 次  {value}")
else:
    print("  （這批資料沒有這個欄位）")

# 價格與座標：確認格式一致、能不能直接拿來運算
print("\n--- 前 5 筆的價格與座標 ---")
for p in properties[:5]:
    rate = (p.get("rate_per_night") or {}).get("extracted_display_price")
    gps = p.get("gps_coordinates") or {}
    print(
        f"  {str(p.get('name'))[:34]:<34} "
        f"每晚={rate!s:<6} "
        f"緯度={gps.get('latitude')!s:<10} 經度={gps.get('longitude')!s:<11} "
        f"type={p.get('type')}"
    )

# nearby_places 的完整結構：這關係到「附近大眾運輸」要怎麼讀
print("\n--- 第一筆的 nearby_places 完整內容 ---")
print(json.dumps(properties[0].get("nearby_places"), ensure_ascii=False, indent=2)
      if properties else "（無資料）")

# 交叉比對：沒有價格的那幾筆，到底是哪一種住宿？
# 這決定「沒價格」能不能當成「沒空房」的判斷依據。
print("\n--- 住宿型態 × 是否有價格 ---")
for p_ in properties:
    pass
from collections import defaultdict
cross = defaultdict(lambda: [0, 0])
for p_ in properties:
    kind = p_.get("type", "(無)")
    has_price = (p_.get("rate_per_night") or {}).get("extracted_display_price") is not None
    cross[kind][0 if has_price else 1] += 1
print(f"  {'型態':<18} {'有價格':>8} {'沒價格':>8}")
for kind, (yes, no) in cross.items():
    print(f"  {kind:<18} {yes:>8} {no:>8}")

print("\n--- 沒有價格的那幾筆長什麼樣 ---")
for p_ in properties:
    if (p_.get("rate_per_night") or {}).get("extracted_display_price") is None:
        print(f"  名稱：{p_.get('name')}")
        print(f"    type        = {p_.get('type')}")
        print(f"    有哪些欄位  = {', '.join(sorted(p_.keys()))}")
        print()

# 照片：SerpApi 的 images 欄位格式沒有文件可查，要看實際長相才知道怎麼取縮圖
print("\n--- images 欄位的結構 ---")
with_images = [p_ for p_ in properties if p_.get("images")]
print(f"  {len(with_images)} / {len(properties)} 筆有 images 欄位")
if with_images:
    sample = with_images[0]["images"]
    print(f"  型別：{type(sample).__name__}，共 {len(sample)} 張")
    first = sample[0]
    print(f"  第一張的型別：{type(first).__name__}")
    if isinstance(first, dict):
        print("  第一張的欄位：")
        for k, v in first.items():
            preview = str(v)
            print(f"    {k:<18} = {preview[:70]}{'…' if len(preview) > 70 else ''}")
    else:
        print(f"  第一張的內容：{str(first)[:100]}")

# 最便宜的幾筆通常就是青年旅館。把它們的完整欄位印出來，
# 看看有沒有比「名稱」和「價格」更可靠的判斷依據。
print("\n--- 最便宜的 6 筆的完整欄位（找更好的過濾訊號用）---")
priced = [p_ for p_ in properties
          if (p_.get("rate_per_night") or {}).get("extracted_display_price") is not None]
priced.sort(key=lambda p_: p_["rate_per_night"]["extracted_display_price"])
for p_ in priced[:6]:
    print(f"\n  ● {p_.get('name')}  "
          f"US${p_['rate_per_night']['extracted_display_price']}")
    for key in ("type", "hotel_class", "extracted_hotel_class", "overall_rating",
                "reviews", "location_rating", "check_in_time", "check_out_time"):
        if key in p_:
            print(f"      {key:<24} {p_[key]}")
    for key in ("amenities", "excluded_amenities"):
        if p_.get(key):
            print(f"      {key:<24} {', '.join(map(str, p_[key]))}")
    desc = p_.get("description")
    if desc:
        text = " ".join(str(desc).split())
        print(f"      {'description':<24} {text[:400]}{'…' if len(text) > 400 else ''}")
    info = p_.get("essential_info")
    if info:
        print(f"      {'essential_info':<24} {info}")
    others = [k for k in p_ if k not in {
        "name", "type", "rate_per_night", "total_rate", "hotel_class",
        "extracted_hotel_class", "overall_rating", "reviews", "location_rating",
        "amenities", "excluded_amenities", "images", "gps_coordinates", "link",
        "property_token", "ratings", "reviews_breakdown", "nearby_places",
        "check_in_time", "check_out_time", "description", "essential_info"}
        and not k.startswith("serpapi")]
    if others:
        print(f"      {'其他欄位':<22} {', '.join(others)}")

print("\n--- 有多少筆缺少關鍵欄位 ---")
for field in ["rate_per_night", "amenities", "gps_coordinates", "nearby_places", "type"]:
    missing = sum(1 for p in properties if not p.get(field))
    print(f"  {field:<18} 缺少 {missing} / {len(properties)} 筆")
print("=" * 60)
