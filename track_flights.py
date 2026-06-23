#!/usr/bin/env python3
"""
김해(PUS) + 인천(ICN) → DAD/CXR/BKK 항공권 가격 매일 추적
SerpAPI Google Flights API 사용
직항편 기준 출발지별 TOP 3 표시
"""

import os
import csv
from datetime import datetime
from pathlib import Path
from itertools import product

import requests

# === 검색 조건 ===
ORIGINS = ["ICN", "PUS"]                    # 인천 + 김해
DESTINATIONS = ["DAD", "CXR", "BKK"]
DEPARTURE_DATE = "2026-08-03"
RETURN_DATES = ["2026-08-08", "2026-08-09"]
ADULTS = 1
CURRENCY = "KRW"

# === API 설정 ===
API_KEY = os.environ.get("SERPAPI_KEY")
BASE_URL = "https://serpapi.com/search"
CSV_FILE = Path(__file__).parent / "flight_prices.csv"


def search_flights(origin, destination, depart, ret):
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": depart,
        "return_date": ret,
        "currency": CURRENCY,
        "adults": ADULTS,
        "type": 1,
        "stops": 1,                 # 1=직항만 (Google Flights API 파라미터)
        "hl": "ko",
        "api_key": API_KEY,
    }
    r = requests.get(BASE_URL, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def parse_flights(data):
    offers = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    parsed = []
    for o in offers:
        price = o.get("price")
        if price is None:
            continue
        flights = o.get("flights", [])
        if not flights:
            continue
        airlines = ",".join(sorted({s.get("airline", "?") for s in flights}))
        parsed.append({
            "price": float(price),
            "airlines": airlines,
            "stops": max(0, len(flights) - 1),
            "depart_at": flights[0].get("departure_airport", {}).get("time", ""),
            "arrive_at": flights[-1].get("arrival_airport", {}).get("time", ""),
            "duration_min": o.get("total_duration", 0),
            "carbon_kg": (o.get("carbon_emissions") or {}).get("this_flight", 0) / 1000,
        })
    parsed.sort(key=lambda x: x["price"])
    return parsed


def fmt_duration(mins):
    if not mins:
        return ""
    h, m = divmod(int(mins), 60)
    return f"{h}h{m:02d}m"


def main():
    if not API_KEY:
        print("❌ SERPAPI_KEY 환경변수가 필요해요.")
        return 1

    now = datetime.now()
    origin_names = {"PUS": "부산", "ICN": "인천"}
    print(f"🛫 {now:%Y-%m-%d %H:%M} | 출발지 {'/'.join(ORIGINS)} → {'/'.join(DESTINATIONS)}")
    print(f"   {DEPARTURE_DATE} 출발 / 귀국 {' or '.join(RETURN_DATES)} / 성인 {ADULTS}명 / 직항만")
    print(f"   총 {len(ORIGINS) * len(DESTINATIONS) * len(RETURN_DATES)}건 조회\n")

    rows = []
    today = now.strftime("%Y-%m-%d")
    # 결과 모음: {(dest, ret): {origin: [direct_flights_sorted_by_price]}}
    by_route = {}

    for origin, dest, ret_date in product(ORIGINS, DESTINATIONS, RETURN_DATES):
        label = f"{origin}→{dest} ({DEPARTURE_DATE}~{ret_date})"
        print(f"  🔍 {label}")
        try:
            data = search_flights(origin, dest, DEPARTURE_DATE, ret_date)
        except requests.HTTPError as e:
            print(f"     ⚠️  HTTP {e.response.status_code}: {e.response.text[:200]}")
            continue
        except requests.RequestException as e:
            print(f"     ⚠️  요청 실패: {e}")
            continue

        if data.get("error"):
            print(f"     ⚠️  {data['error']}")
            continue

        parsed = parse_flights(data)
        # 직항만 필터링 (Google API의 stops=1 파라미터가 적용되지만 한번 더 확인)
        direct = [p for p in parsed if p["stops"] == 0]

        if not direct:
            print(f"     (직항편 없음)")
            continue

        insights = data.get("price_insights") or {}
        level = insights.get("price_level", "")
        level_emoji = {"low": "🟢싸요", "typical": "🟡보통", "high": "🔴비싸요"}.get(level, "")
        typical = insights.get("typical_price_range", [])

        best = direct[0]
        print(f"     💰 {best['price']:>9,.0f} KRW  "
              f"{best['airlines']} / 직항 / {fmt_duration(best['duration_min'])}  "
              f"{level_emoji}")

        # 결과 정리
        by_route.setdefault((dest, ret_date), {})[origin] = direct[:3]

        # CSV용 (직항 상위 5개)
        for rank, p in enumerate(direct[:5], 1):
            rows.append({
                "check_date": today,
                "origin": origin,
                "destination": dest,
                "depart_date": DEPARTURE_DATE,
                "return_date": ret_date,
                "rank": rank,
                "price_krw": p["price"],
                "airlines": p["airlines"],
                "stops": p["stops"],
                "depart_time": p["depart_at"],
                "arrive_time": p["arrive_at"],
                "duration_min": p["duration_min"],
                "carbon_kg": round(p["carbon_kg"], 1),
                "price_level": level,
                "typical_low": typical[0] if typical else "",
                "typical_high": typical[1] if typical else "",
            })

    if rows:
        new_file = not CSV_FILE.exists()
        with CSV_FILE.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            if new_file:
                w.writeheader()
            w.writerows(rows)
        print(f"\n📝 {len(rows)}건 → {CSV_FILE.name}")

    # 출발지별 TOP 3 출력
    if by_route:
        print("\n" + "=" * 70)
        print("📊 오늘의 직항 최저가 TOP 3 (출발지별)")
        print("=" * 70)
        medals = ["🥇", "🥈", "🥉"]
        for (dest, ret), origins_data in sorted(by_route.items()):
            print(f"\n  🌴 {dest} / 귀국 {ret}")
            for origin in ORIGINS:  # ICN, PUS 순서 고정
                items = origins_data.get(origin, [])
                origin_label = f"[{origin_names[origin]} {origin}]"
                if not items:
                    print(f"     {origin_label} 직항 없음")
                    continue
                for i, p in enumerate(items[:3]):
                    print(f"     {medals[i]} {origin_label} {p['price']:>9,.0f} KRW  "
                          f"{p['airlines']} ({fmt_duration(p['duration_min'])})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
