"""
chuseok_watch.py — 김해(PUS) 출발 동남아 6개 노선 최저가 감시
대상 일정: 2026-09-20 출국 / 2026-09-24 귀국 (직항 왕복)
알림 기준: 300,000 KRW 이하

기존 트래커와 동일하게 SERPAPI_KEY 환경변수를 사용합니다.
GitHub Actions에서 돌릴 경우 cron: "0 */3 * * *" 정도(3시간 간격)를 권장.
2주 남은 일정이라 하루 1회로는 특가를 놓칠 수 있습니다.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

SERPAPI_KEY = os.environ["SERPAPI_KEY"]
ENDPOINT = "https://serpapi.com/search"

THRESHOLD_KRW = 300_000
HISTORY_PATH = Path("data/chuseok_history.json")
KST = timezone(timedelta(hours=9))

# 공급이 많은 노선부터. 방콕은 수완나품(BKK)/돈므앙(DMK) 둘 다 조회.
ROUTES = [
    ("푸꾸옥",   "PQC"),
    ("나트랑",   "CXR"),
    ("방콕",     "BKK"),
    ("방콕(DMK)", "DMK"),
    ("호치민",   "SGN"),
    ("하노이",   "HAN"),
    ("치앙마이", "CNX"),
]

# 앞뒤 하루씩 흔들어 봅니다. 귀국 9/25는 추석 당일이라 제외.
DATE_PAIRS = [
    ("2026-09-20", "2026-09-24"),
    ("2026-09-19", "2026-09-24"),
    ("2026-09-20", "2026-09-23"),
]


def query(dest_code: str, outbound: str, inbound: str) -> dict | None:
    """직항 왕복 최저가 1건을 반환. 결과 없으면 None."""
    params = {
        "engine": "google_flights",
        "api_key": SERPAPI_KEY,
        "departure_id": "PUS",
        "arrival_id": dest_code,
        "outbound_date": outbound,
        "return_date": inbound,
        "type": "1",        # 왕복
        "stops": "1",       # 직항만
        "travel_class": "1",
        "adults": "1",
        "currency": "KRW",
        "hl": "ko",
        "gl": "kr",
        "deep_search": "true",
    }
    r = requests.get(ENDPOINT, params=params, timeout=45)
    r.raise_for_status()
    data = r.json()

    flights = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    if not flights:
        return None

    cheapest = min(
        (f for f in flights if f.get("price")),
        key=lambda f: f["price"],
        default=None,
    )
    if not cheapest:
        return None

    legs = cheapest.get("flights", [])
    return {
        "price": cheapest["price"],
        "airline": legs[0].get("airline") if legs else None,
        "depart_time": legs[0].get("departure_airport", {}).get("time") if legs else None,
        "duration_min": cheapest.get("total_duration"),
    }


def main() -> None:
    stamp = datetime.now(KST).isoformat(timespec="minutes")
    rows = []

    for label, code in ROUTES:
        for outbound, inbound in DATE_PAIRS:
            try:
                hit = query(code, outbound, inbound)
            except Exception as exc:  # 한 노선 실패가 전체를 막지 않도록
                print(f"  ! {label} {outbound}~{inbound}: {exc}")
                continue

            if not hit:
                print(f"  - {label} {outbound}~{inbound}: 직항 없음")
                continue

            rows.append({
                "checked_at": stamp,
                "dest": label,
                "code": code,
                "outbound": outbound,
                "inbound": inbound,
                **hit,
            })

    rows.sort(key=lambda r: r["price"])

    print(f"\n=== {stamp} · 김해 출발 직항 왕복 ===")
    for r in rows:
        flag = "★" if r["price"] <= THRESHOLD_KRW else " "
        print(
            f"{flag} {r['price']:>8,}원  {r['dest']:<9} "
            f"{r['outbound'][5:]}~{r['inbound'][5:]}  {r['airline'] or ''}"
        )

    hits = [r for r in rows if r["price"] <= THRESHOLD_KRW]
    if hits:
        best = hits[0]
        print(f"\n>>> 기준가 도달: {best['dest']} {best['price']:,}원 <<<")
        # GitHub Actions step output으로 넘겨 알림 트리거에 사용
        if out := os.environ.get("GITHUB_OUTPUT"):
            with open(out, "a") as fh:
                fh.write(f"alert=true\n")
                fh.write(f"alert_text={best['dest']} {best['price']:,}원\n")

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else []
    history.extend(rows)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
