"""
讀取 check_serpapi.py 存下來的 serpapi_sample.json，
整理出我需要知道的資訊。

這支程式「不會連網」，所以不會消耗任何 SerpApi 額度，可以放心重複執行。

執行方式：
    python show_sample.py
"""

import json
from collections import Counter
from pathlib import Path

SAMPLE = Path(__file__).parent / "serpapi_sample.json"

if not SAMPLE.exists():
    raise SystemExit("找不到 serpapi_sample.json，請先執行 python check_serpapi.py")

data = json.loads(SAMPLE.read_text(encoding="utf-8"))
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

print("\n--- 有多少筆缺少關鍵欄位 ---")
for field in ["rate_per_night", "amenities", "gps_coordinates", "nearby_places", "type"]:
    missing = sum(1 for p in properties if not p.get(field))
    print(f"  {field:<18} 缺少 {missing} / {len(properties)} 筆")
print("=" * 60)
