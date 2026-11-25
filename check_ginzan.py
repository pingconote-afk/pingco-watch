"""
銀山溫泉組合 (nj-yoyaku.net) 空房檢查
- 檢查指定日期範圍每晚、指定人數的空房
- 以「日期 × 人數 × 旅館」為單位追蹤：
    🆕 新出現空房 → 寄信通知一次
    ❌ 之前有、現在沒了 → 寄信通知一次
    同樣的空房持續存在 → 不重複寄信
- 只用 Python 標準函式庫，不需要安裝任何套件

環境變數（在 GitHub Secrets 設定）：
  GMAIL_USER          寄件的 Gmail 帳號
  GMAIL_APP_PASSWORD  Gmail「應用程式密碼」（16 碼，不是登入密碼）
  MAIL_TO             收件人，可填多個、用逗號分隔（可省略，預設 = GMAIL_USER）
  TEST_EMAIL          設為 1 時只寄一封測試信
"""

import datetime as dt
import json
import os
import re
import smtplib
import sys
import time
import urllib.request
from email.mime.text import MIMEText
from html import unescape
from pathlib import Path

# ===== 可以自行修改的設定 =====
START = dt.date(2027, 2, 1)
END = dt.date(2027, 3, 10)
PEOPLE = [2, 4]
ONLY_INNS = []  # 例如 ["能登屋旅館", "ホテル　藤屋"]；空的 = 全部 11 間都通知
NOTIFY_GONE = True  # True = 之前通知過的空房消失時也寄信
# =============================

BASE = "https://www.nj-yoyaku.net"
SEARCH = BASE + "/portal/search?date={date}&nz={nz}&pref=6&area=0&onse=10&city=0"
NO_PLAN = "表示できるプランがございません"
STATE_FILE = Path(__file__).with_name("last_hits.json")
WEEKDAY = "一二三四五六日"
TW = dt.timezone(dt.timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,zh-TW;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def inn_names(html: str) -> list[str]:
    names = re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=re.S | re.I)
    names = [unescape(re.sub(r"<[^>]+>", "", n)).strip() for n in names]
    return list(dict.fromkeys(n for n in names if n))


def key(s: dict) -> str:
    return f"{s['date']}|{s['people']}|{s['inn']}"


def check() -> tuple[dict, set]:
    """回傳 (目前空房 {key: slot}, 查詢失敗的 {(date, people)})"""
    slots, failed = {}, set()
    d = START
    while d <= END:
        for nz in PEOPLE:
            url = SEARCH.format(date=d.isoformat(), nz=nz)
            try:
                html = fetch(url)
            except Exception as e:
                print(f"[WARN] {d} {nz}名 查詢失敗: {e}", file=sys.stderr)
                failed.add((d.isoformat(), nz))
                time.sleep(2)
                continue
            if NO_PLAN not in html:
                inns = inn_names(html) or ["（旅館名稱解析失敗）"]
                for inn in inns:
                    if ONLY_INNS and inn not in ONLY_INNS:
                        continue
                    s = {"date": d.isoformat(), "people": nz, "inn": inn, "url": url}
                    slots[key(s)] = s
            time.sleep(1)  # 對網站客氣一點
        d += dt.timedelta(days=1)
    return slots, failed


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    data = json.loads(STATE_FILE.read_text("utf-8"))
    out = {}
    for h in data:
        if "inn" in h:
            out[key(h)] = h
        else:  # 舊版格式（inns 為清單）
            for inn in h.get("inns") or ["（旅館名稱解析失敗）"]:
                s = {"date": h["date"], "people": h["people"], "inn": inn, "url": h["url"]}
                out[key(s)] = s
    return out


def send_mail(subject: str, body: str) -> None:
    user = os.environ["GMAIL_USER"]
    pwd = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    # MAIL_TO 可填多個收件人，用逗號分隔，例如 "a@gmail.com, b@gmail.com"
    raw = os.environ.get("MAIL_TO") or user
    to_list = [x.strip() for x in re.split(r"[,;\s]+", raw) if x.strip()]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(to_list)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pwd)
        s.sendmail(user, to_list, msg.as_string())
    print(f"已寄出通知給 {len(to_list)} 位收件人")


def label(s: dict) -> str:
    d = dt.date.fromisoformat(s["date"])
    return f"{d.month}/{d.day}（週{WEEKDAY[d.weekday()]}）{s['people']}名：{s['inn']}"


def sort_slots(xs):
    return sorted(xs, key=lambda s: (s["date"], s["people"], s["inn"]))


def main() -> None:
    if os.environ.get("TEST_EMAIL") == "1":
        send_mail("🔔 銀山溫泉空房通知：測試信",
                  "GitHub Actions 的 Email 設定成功！\n"
                  f"檢查範圍：{START}～{END}，{'/'.join(map(str, PEOPLE))}名。")
        return

    now_slots, failed = check()
    old_slots = load_state()

    # 查詢失敗的日期/人數：沿用上次的狀態，避免誤判成「沒了」
    for k, s in old_slots.items():
        if (s["date"], s["people"]) in failed:
            now_slots.setdefault(k, s)

    new = sort_slots(s for k, s in now_slots.items() if k not in old_slots)
    gone = sort_slots(s for k, s in old_slots.items() if k not in now_slots)
    still = sort_slots(s for k, s in now_slots.items() if k in old_slots)

    print(f"檢查完成：目前空房 {len(now_slots)} 筆，新出現 {len(new)}，消失 {len(gone)}，查詢失敗 {len(failed)}")

    if not NOTIFY_GONE:
        gone = []

    if new or gone:
        now = dt.datetime.now(TW).strftime("%m/%d %H:%M")
        body = f"銀山溫泉空房變動（台灣時間 {now} 確認）\n"
        if new:
            body += "\n🆕 新出現空房（請盡快預約）：\n"
            body += "\n".join(f"• {label(s)}\n  {s['url']}" for s in new) + "\n"
        if gone:
            body += "\n❌ 已經沒有了（之前通知過的空房）：\n"
            body += "\n".join(f"• {label(s)}" for s in gone) + "\n"
        if still:
            body += "\n⏳ 目前仍有空房（之前通知過，供參考）：\n"
            body += "\n".join(f"• {label(s)}\n  {s['url']}" for s in still) + "\n"
        if not now_slots:
            body += "\n目前檢查範圍內已經沒有任何空房。\n"

        parts = []
        if new:
            parts.append(f"🆕 新空房 {len(new)} 筆")
        if gone:
            parts.append(f"❌ 沒了 {len(gone)} 筆")
        send_mail(f"銀山溫泉：{'、'.join(parts)}（{now}）", body)
    else:
        print("空房沒有變動，不寄信。")

    STATE_FILE.write_text(json.dumps(sort_slots(now_slots.values()), ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()
