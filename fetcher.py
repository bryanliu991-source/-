"""
fetcher.py — 数据抓取模块
负责三件事：
  1. 从天天基金抓取易方达全球成长精选的最新季报持仓
  2. 从 AKShare 抓取自选股实时行情
  3. 从财联社 RSS 抓取今日宏观新闻
"""

import json
import os
import requests
import feedparser
from datetime import datetime, date

# ── 你可以在这里修改自选股列表 ──────────────────────────────
WATCHLIST = [
    {"name": "赣锋锂业", "code": "002460"},
    {"name": "兴德盛",   "code": "603344"},
    {"name": "天健科技", "code": "002888"},  # 如有 ST 前缀仍用原代码
]
# ─────────────────────────────────────────────────────────────

# ── 1. 易方达全球成长精选持仓 ─────────────────────────────────
def fetch_fund_holdings():
    """
    天天基金提供基金持仓的 JSON 接口。
    006228 = 易方达全球成长精选混合（QDII）
    返回前10大持仓列表，格式：[{name, weight, change}, ...]
    注意：数据来自最新季报，有 1~2 个月滞后，这是公募基金法规要求，无法绕过。
    """
    fund_code = "006228"
    url = f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={fund_code}&topline=10"
    
    headers = {
        "Referer": "https://fundf10.eastmoney.com/",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "utf-8"
        text = resp.text
        
        # 天天基金返回的是 JS 变量赋值格式，需要提取 JSON 部分
        # 格式：var apidata={ content:"...", arryList:[...], ... }
        import re
        match = re.search(r'arryList:\[(.*?)\]', text, re.DOTALL)
        if not match:
            return {"error": "无法解析持仓数据", "holdings": [], "report_date": "未知"}
        
        # 提取报告期
        date_match = re.search(r'截止日期[：:]\s*([\d\-年月日]+)', text)
        report_date = date_match.group(1) if date_match else "最新季报"
        
        # 解析每一行持仓（天天基金用 HTML 表格，改用另一个接口更稳定）
        # 备用：直接请求基金持仓详情页的表格数据
        detail_url = f"https://fundf10.eastmoney.com/ccmx_{fund_code}.html"
        resp2 = requests.get(detail_url, headers=headers, timeout=10)
        resp2.encoding = "utf-8"
        
        from html.parser import HTMLParser
        
        class HoldingParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.holdings = []
                self.in_table = False
                self.current_row = []
                self.in_td = False
                self.td_text = ""
                self.row_count = 0
                
            def handle_starttag(self, tag, attrs):
                attrs_dict = dict(attrs)
                if tag == "table" and "jjcc_table" in attrs_dict.get("class", ""):
                    self.in_table = True
                if self.in_table and tag == "tr":
                    self.current_row = []
                if self.in_table and tag == "td":
                    self.in_td = True
                    self.td_text = ""
                    
            def handle_endtag(self, tag):
                if self.in_table and tag == "td":
                    self.in_td = False
                    self.current_row.append(self.td_text.strip())
                if self.in_table and tag == "tr":
                    if len(self.current_row) >= 4 and self.row_count > 0:
                        self.holdings.append({
                            "name": self.current_row[1] if len(self.current_row) > 1 else "",
                            "weight": self.current_row[3] if len(self.current_row) > 3 else "",
                        })
                    self.row_count += 1
                if tag == "table":
                    self.in_table = False
                    
            def handle_data(self, data):
                if self.in_td:
                    self.td_text += data
        
        parser = HoldingParser()
        parser.feed(resp2.text)
        
        holdings = parser.holdings[:10]
        
        # 如果 HTML 解析失败，返回一个说明
        if not holdings:
            return {
                "fund_name": "易方达全球成长精选混合(QDII)",
                "fund_code": fund_code,
                "report_date": report_date,
                "holdings": [],
                "note": "持仓数据解析失败，请访问 https://fundf10.eastmoney.com/ccmx_006228.html 查看"
            }
        
        return {
            "fund_name": "易方达全球成长精选混合(QDII)",
            "fund_code": fund_code,
            "report_date": report_date,
            "holdings": holdings
        }
        
    except Exception as e:
        return {
            "fund_name": "易方达全球成长精选混合(QDII)",
            "fund_code": fund_code,
            "report_date": "获取失败",
            "holdings": [],
            "error": str(e)
        }


# ── 2. 自选股行情 ─────────────────────────────────────────────
def fetch_watchlist_quotes():
    """
    用新浪财经的实时行情接口抓取自选股数据。
    不需要安装 akshare，直接用 requests，更稳定。
    返回格式：[{name, code, price, change_pct, change_amt}, ...]
    """
    results = []
    
    for stock in WATCHLIST:
        code = stock["code"]
        name = stock["name"]
        
        # 判断是沪市（6开头）还是深市（0/3开头）
        if code.startswith("6"):
            sina_code = f"sh{code}"
        else:
            sina_code = f"sz{code}"
        
        url = f"https://hq.sinajs.cn/list={sina_code}"
        headers = {
            "Referer": "https://finance.sina.com.cn/",
            "User-Agent": "Mozilla/5.0"
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            resp.encoding = "gbk"  # 新浪接口用 GBK 编码
            text = resp.text
            
            # 格式：var hq_str_sh600000="浦发银行,10.38,10.30,10.45,10.50,10.35,..."
            import re
            match = re.search(r'"([^"]+)"', text)
            if match:
                parts = match.group(1).split(",")
                if len(parts) > 6:
                    price = float(parts[3])       # 当前价
                    prev_close = float(parts[2])  # 昨收
                    change_amt = round(price - prev_close, 2)
                    change_pct = round((change_amt / prev_close) * 100, 2) if prev_close else 0
                    
                    results.append({
                        "name": name,
                        "code": code,
                        "price": price,
                        "change_pct": change_pct,
                        "change_amt": change_amt,
                        "prev_close": prev_close,
                        "high": float(parts[4]),
                        "low": float(parts[5]),
                        "volume": parts[8],  # 成交量（手）
                    })
                else:
                    results.append({"name": name, "code": code, "error": "数据格式异常"})
            else:
                results.append({"name": name, "code": code, "error": "无法解析"})
                
        except Exception as e:
            results.append({"name": name, "code": code, "error": str(e)})
    
    return results


# ── 3. 宏观新闻 RSS ───────────────────────────────────────────
def fetch_macro_news(max_items=6):
    """
    从多个财经 RSS 源抓取今日新闻，合并去重后返回最新的 max_items 条。
    数据源：财联社、路透中文、新浪财经
    """
    RSS_SOURCES = [
        {
            "name": "财联社",
            "url": "https://www.cls.cn/rss"
        },
        {
            "name": "路透中文",
            "url": "https://feeds.reuters.com/reuters/CNTopNews"
        },
        {
            "name": "新浪财经",
            "url": "https://rss.sina.com.cn/news/global/finance_and_economics.xml"
        },
    ]
    
    all_news = []
    
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:5]:  # 每个源最多取5条
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                published = entry.get("published", "")
                
                if title:
                    all_news.append({
                        "source": source["name"],
                        "title": title,
                        "link": link,
                        "published": published,
                    })
        except Exception as e:
            # RSS 抓取失败不中断，跳过这个源
            print(f"RSS 源 {source['name']} 抓取失败: {e}")
            continue
    
    # 按发布时间排序，取最新的 max_items 条
    # feedparser 会尝试解析时间，放在 published_parsed 字段
    return all_news[:max_items]


# ── 主函数：汇总所有数据 ─────────────────────────────────────
def fetch_all():
    """
    统一入口，返回完整的早报数据字典。
    brief_generator.py 会调用这个函数。
    """
    print("📡 正在抓取基金持仓...")
    fund_data = fetch_fund_holdings()
    
    print("📈 正在抓取自选股行情...")
    quotes = fetch_watchlist_quotes()
    
    print("📰 正在抓取宏观新闻...")
    news = fetch_macro_news()
    
    return {
        "date": date.today().isoformat(),
        "fund": fund_data,
        "watchlist": quotes,
        "news": news,
    }


if __name__ == "__main__":
    # 直接运行这个文件可以测试数据抓取是否正常
    data = fetch_all()
    print(json.dumps(data, ensure_ascii=False, indent=2))
