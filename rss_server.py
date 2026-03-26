from fastapi import FastAPI, Response
from datetime import datetime

app = FastAPI()

def build_rss(items, title):
    rss_items = ""
    for item in items:
        rss_items += f"""
        <item>
            <title>{item['title']}</title>
            <description>{item['desc']}</description>
            <pubDate>{item['date']}</pubDate>
        </item>
        """

    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>{title}</title>
        <link>https://poddedprofits.com</link>
        <description>EVE Online Intel Feed</description>
        {rss_items}
      </channel>
    </rss>"""

@app.get("/rss/trade-routes.xml")
def trade_routes():
    # replace with your SQL results
    items = [
        {
            "title": "Jita → Amarr | HOT",
            "desc": "Kills: 42 | Risk: HIGH | Profit: 18%",
            "date": datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
        }
    ]
    xml = build_rss(items, "PoddedProfits Trade Routes")
    return Response(content=xml, media_type="application/xml")