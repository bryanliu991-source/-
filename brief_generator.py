"""
brief_generator.py — 早报生成模块
把 fetcher.py 抓到的原始数据喂给 Claude API，
生成一段结构化的中文早报文字，然后推送到微信（Server酱）。
"""

import json
import os
import requests
from fetcher import fetch_all

# ── Server酱 SendKey（从环境变量读取）────────────────────────
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")

# ── Anthropic API Key（从环境变量读取）───────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# ── 1. 调用 Claude API 生成早报文字 ─────────────────────────
def generate_brief_text(data: dict) -> str:
    fund = data.get("fund", {})
    watchlist = data.get("watchlist", [])
    news = data.get("news", [])
    today = data.get("date", "今日")

    holdings_text = ""
    if fund.get("holdings"):
        for h in fund["holdings"]:
            holdings_text += f"  - {h.get('name', '')}：占比 {h.get('weight', '')}\n"
    else:
        holdings_text = "  （持仓数据暂时无法获取）"

    watchlist_text = ""
    for q in watchlist:
        if "error" not in q:
            sign = "+" if q["change_pct"] >= 0 else ""
            watchlist_text += f"  - {q['name']}（{q['code']}）：{q['price']} 元，{sign}{q['change_pct']}%\n"
        else:
            watchlist_text += f"  - {q['name']}（{q['code']}）：数据获取失败\n"

    news_text = ""
    for n in news[:5]:
        news_text += f"  - [{n.get('source', '')}] {n.get('title', '')}\n"

    prompt = f"""今天是 {today}，请根据以下数据生成一份简洁的金融早报。

【易方达全球成长精选（006228）最新季报持仓 — {fund.get('report_date', '未知')}】
{holdings_text}

【自选股今日行情（A股）】
{watchlist_text if watchlist_text else '  （暂无数据）'}

【今日宏观新闻】
{news_text if news_text else '  （暂无数据）'}

请用以下格式输出，语言简洁专业：
第一段：用1-2句话概括今日市场情绪和关键宏观事件。
第二段：说明基金持仓当前结构特点，提醒数据来自季报有滞后。
第三段：对自选股的简要点评，关注涨跌异动。
最后一行：一句话今日关注重点。
控制在300字以内，不要用markdown格式，直接输出纯文字。"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=30
        )
        resp.raise_for_status()
        result = resp.json()
        return result["content"][0]["text"]
    except Exception as e:
        return f"AI 摘要生成失败：{e}\n请检查 ANTHROPIC_API_KEY 是否正确配置。"


# ── 2. 推送到微信（Server酱）─────────────────────────────────
def send_to_wechat(title: str, content: str) -> bool:
    if not SERVERCHAN_KEY:
        print("❌ 未配置 SERVERCHAN_KEY，跳过推送")
        return False

    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"

    try:
        resp = requests.post(
            url,
            data={"title": title, "desp": content},
            timeout=10
        )
        result = resp.json()
        if result.get("data", {}).get("errno") == 0 or result.get("code") == 0:
            print("✅ 早报推送成功，请查看微信")
            return True
        else:
            print(f"❌ 推送失败：{result}")
            return False
    except Exception as e:
        print(f"❌ 推送异常：{e}")
        return False


# ── 3. 格式化消息 ─────────────────────────────────────────────
def format_message(data: dict, ai_summary: str) -> tuple:
    today = data.get("date", "")
    watchlist = data.get("watchlist", [])

    stock_lines = []
    for q in watchlist:
        if "error" not in q:
            sign = "+" if q["change_pct"] >= 0 else ""
            arrow = "▲" if q["change_pct"] >= 0 else "▼"
            stock_lines.append(f"- {q['name']}（{q['code']}）{q['price']} 元  {arrow}{sign}{q['change_pct']}%")
        else:
            stock_lines.append(f"- {q['name']}  数据异常")

    stocks_block = "\n".join(stock_lines) if stock_lines else "暂无数据"

    title = f"📋 金融早报 {today}"
    content = f"""{ai_summary}

---

**自选股行情**

{stocks_block}

---

> 基金持仓数据来自公开季报，存在1-2个月滞后。本早报仅供参考，不构成投资建议。"""

    return title, content


# ── 主流程 ────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("🌅 金融早报生成开始")
    print("=" * 50)

    print("\n[1/3] 抓取市场数据...")
    data = fetch_all()

    print("\n[2/3] 调用 Claude API 生成摘要...")
    if ANTHROPIC_API_KEY:
        ai_summary = generate_brief_text(data)
    else:
        ai_summary = "未配置 ANTHROPIC_API_KEY，跳过 AI 摘要生成。"

    print("\n生成的摘要：")
    print(ai_summary)

    print("\n[3/3] 推送到微信...")
    title, content = format_message(data, ai_summary)
    send_to_wechat(title, content)

    print("\n🏁 早报生成完成")


if __name__ == "__main__":
    main()
