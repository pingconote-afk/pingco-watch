"""
銀山溫泉組合 (nj-yoyaku.net) 空房檢查
- 檢查 2027/02/01–02/28 每晚，2名 / 4名
- 有「新的」空房時寄 Gmail 通知（同樣的空房不會重複寄）
- 只用 Python 標準函式庫，不需要安裝任何套件

環境變數（在 GitHub Secrets 設定）：
  GMAIL_USER          寄件的 Gmail 帳號，例如 youping421.ai@gmail.com
  GMAIL_APP_PASSWORD  Gmail「應用程式密碼」（16 碼，不是登入密碼）
  MAIL_TO             收件人（可省略，預設 = GMAIL_USER）
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
# =============================

BASE = "https://www.nj-yoyaku.net"
SEARCH = BASE + "/portal/search?date={date}&nz={nz}&pref=6&area=0&onse=10&city=0"
NO_PLAN = "表示できるプランがございません"
STATE_FILE = Path(__file__).with_name("last_hits.json")
WEEKDAY = "一二三四五六日"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,zh-TW;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def inn_names(html: str) -> list[str]:
    names = re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=re.S | re.I)
    names = [unescape(re.sub(r"<[^>]+>", "", n)).strip() for n in names]
    return list(dict.fromkeys(n for n in names if n))


def check() -> list[dict]:
    hits = []
    d = START
    while d <= END:
        for nz in PEOPLE:
            url = SEARCH.format(date=d.isoformat(), nz=nz)
            try:
                html = fetch(url)
            except Exception as e:  # 單一查詢失敗不影響其他日期
                print(f"[WARN] {d} {nz}名 查詢失敗: {e}", file=sys.stderr)
                time.sleep(2)
                continue
            if NO_PLAN not in html:
                inns = inn_names(html)
                if ONLY_INNS:
                    inns = [i for i in inns if i in ONLY_INNS]
                if inns or not ONLY_INNS:
                    hits.append({"date": d.isoformat(), "people": nz, "inns": inns, "url": url})
            time.sleep(1)  # 對網站客氣一點
        d += dt.timedelta(days=1)
    return hits


def send_mail(subject: str, body: str) -> None:
    user = os.environ["GMAIL_USER"]
    pwd = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    to = os.environ.get("MAIL_TO") or user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())
    print(f"已寄出通知到 {to}")


def fmt(h: dict) -> str:
    d = dt.date.fromisoformat(h["date"])
    inns = "、".join(h["inns"]) or "（旅館名稱解析失敗，請點連結查看）"
    return f"• {d.month}/{d.day}（週{WEEKDAY[d.weekday()]}）{h['people']}名：{inns}\n  {h['url']}"


def main() -> None:
    if os.environ.get("TEST_EMAIL") == "1":
        send_mail("🔔 銀山溫泉空房通知：測試信",
                  "GitHub Actions 的 Email 設定成功！\n"
                  f"檢查範圍：{START}～{END}，{'/'.join(map(str, PEOPLE))}名。")
        return

    hits = check()
    print(f"檢查完成，有空房的組合：{len(hits)}")
    for h in hits:
        print(fmt(h))

    old = json.loads(STATE_FILE.read_text("utf-8")) if STATE_FILE.exists() else []
    old_keys = {(h["date"], h["people"], tuple(h["inns"])) for h in old}
    new = [h for h in hits if (h["date"], h["people"], tuple(h["inns"])) not in old_keys]

    if new:
        body = "🎉 銀山溫泉有新的空房！\n\n" + "\n".join(fmt(h) for h in new)
        body += "\n\n空房可能很快被訂走，請盡快自行預約。"
        send_mail(f"🎉 銀山溫泉有空房！（{len(new)} 筆）", body)
    else:
        print("沒有新的空房，不寄信。")

    STATE_FILE.write_text(json.dumps(hits, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()
