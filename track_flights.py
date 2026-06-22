#!/usr/bin/env python3
"""
김해(PUS) → DAD/CXR/BKK 항공권 가격 매일 추적
SerpAPI Google Flights API 사용
무료 등급: 월 250건 검색 / 우리는 월 180건 사용
"""

import os
import csv
from datetime import datetime
from pathlib import Path
from itertools import product

import requests

# === 검색 조건 ===
ORIGIN = "PUS"                              # 김해
DESTINATIONS = ["DAD", "CXR", "BKK"]        # 다낭 / 나트랑(깜라인) / 방콕
DEPARTURE_DATE = "2026-08-03"
RETURN_DATES = ["2026-08-08", "2026-08-09"]
ADULTS = 1
CURRENCY = "KRW"

# === API 설정 ===
API_KEY = os.environ.get("SERPAPI_KEY")
BASE_URL = "https://serpapi.com/search"

CSV_FILE = Path(__file__).parent / "flight_prices.csv"


def search_flights(origin, destination, depart, ret):
    """SerpAPI Google Flights 호출 (왕복, 첫 호출이면 총 왕복가 반환)"""
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": depart,
        "return_date": ret,
        "currency": CURRENCY,
        "adults": ADULTS,
        "type": 1,                  # 1=Round trip
        "hl": "ko",
        "api_key": API_KEY,
    }
    r = requests.get(BASE_URL, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def parse_flights(data):
    """best_flights + other_flights에서 가격 정보 추출, 가격순 정렬"""
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
        print("   https://serpapi.com 가입 후 Dashboard에서 API Key 복사")
        return 1

    now = datetime.now()
    print(f"🛫 {now:%Y-%m-%d %H:%M} | {ORIGIN} → {'/'.join(DESTINATIONS)}")
    print(f"   {DEPARTURE_DATE} 출발 / 귀국 {' or '.join(RETURN_DATES)} / 성인 {ADULTS}명\n")

    rows = []
    summary = []
    today = now.strftime("%Y-%m-%d")

    for dest, ret_date in product(DESTINATIONS, RETURN_DATES):
        label = f"{ORIGIN}→{dest} ({DEPARTURE_DATE}~{ret_date})"
        print(f"  🔍 {label}")
        try:
            data = search_flights(ORIGIN, dest, DEPARTURE_DATE, ret_date)
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
        if not parsed:
            print("     (결과 없음)")
            continue

        best = parsed[0]
        insights = data.get("price_insights") or {}
        level = insights.get("price_level", "")
        level_emoji = {"low": "🟢싸요", "typical": "🟡보통", "high": "🔴비싸요"}.get(level, "")
        typical = insights.get("typical_price_range", [])

        print(f"     💰 최저가 {best['price']:>9,.0f} KRW  "
              f"{best['airlines']} / {best['stops']}경유 / {fmt_duration(best['duration_min'])}  "
              f"{level_emoji}")
        if typical:
            print(f"     📊 평소 가격대: {typical[0]:,} ~ {typical[1]:,} KRW")

        summary.append({
            "dest": dest, "ret": ret_date,
            "price": best["price"], "airline": best["airlines"],
            "level": level,
        })

        for rank, p in enumerate(parsed, 1):
            rows.append({
                "check_date": today,
                "origin": ORIGIN, "destination": dest,
                "depart_date": DEPARTURE_DATE, "return_date": ret_date,
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

    if summary:
        summary.sort(key=lambda x: x["price"])
        print("\n" + "=" * 60)
        print("📊 오늘의 최저가 TOP")
        print("=" * 60)
        for i, r in enumerate(summary, 1):
            mark = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
            level_tag = {"low": " 🟢", "high": " 🔴"}.get(r["level"], "")
            print(f"  {mark} {r['dest']} / 귀국 {r['ret']}  "
                  f"{r['price']:>10,.0f} KRW  [{r['airline']}]{level_tag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
