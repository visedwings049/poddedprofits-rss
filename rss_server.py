from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Dict, List, Any
from xml.sax.saxutils import escape

from dotenv import load_dotenv
from fastapi import FastAPI, Response
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = FastAPI()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "port": int(os.getenv("DB_PORT", "5432")),
}

SUMMARY_SQL = """
select
    route_id,
    route_name,
    route_type,
    sort_order,
    system_count,
    total_score,
    danger_density,
    hot_system_count,
    active_system_count,
    warm_system_count,
    live_spike_systems,
    primary_threat,
    risk_level,
    route_temperature
from trade_route_summary_v2
order by sort_order, route_id;
"""

DETAIL_SQL = """
select
    route_id,
    route_name,
    route_type,
    sort_order,
    system_index,
    system_name,
    clusters_2m,
    clusters_5m,
    clusters_15m,
    kills_2m,
    kills_5m,
    kills_15m,
    system_score,
    system_heat
from trade_route_detail_v2
order by sort_order, route_id, system_index;
"""


def rfc2822_now() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def make_guid(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def fetch_rows(conn, sql: str) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        return [dict(row) for row in cur.fetchall()]


def get_trade_route_data() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        summary_rows = fetch_rows(conn, SUMMARY_SQL)
        detail_rows = fetch_rows(conn, DETAIL_SQL)
        return summary_rows, detail_rows
    finally:
        conn.close()


def build_detail_map(detail_rows: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    detail_map: Dict[int, List[Dict[str, Any]]] = {}
    for row in detail_rows:
        detail_map.setdefault(row["route_id"], []).append(row)
    return detail_map


def format_path(details: List[Dict[str, Any]]) -> str:
    if not details:
        return "No path available"
    return " → ".join(str(row["system_name"]) for row in details)


def compact_activity(details: List[Dict[str, Any]], max_systems: int = 6) -> str:
    if not details:
        return "No activity detail available"

    parts: List[str] = []
    for row in details[:max_systems]:
        parts.append(
            f'{row["system_name"]} '
            f'[{row["kills_2m"]}/{row["clusters_2m"]}, '
            f'{row["kills_5m"]}/{row["clusters_5m"]}, '
            f'{row["kills_15m"]}/{row["clusters_15m"]}] '
            f'{row["system_heat"]}'
        )

    extra = len(details) - max_systems
    if extra > 0:
        parts.append(f"+{extra} more systems")

    return " | ".join(parts)


def summarize_route(summary: Dict[str, Any], details: List[Dict[str, Any]]) -> dict[str, str]:
    path_text = format_path(details)

    title = f'{summary["route_name"]} | {summary["route_temperature"]}'
    description = (
        f'Path: {path_text}\n'
        f'Type: {summary["route_type"].title()} | '
        f'Risk: {summary["risk_level"]} | '
        f'Threat Score: {summary["total_score"]} | '
        f'Danger Density: {summary["danger_density"]}\n'
        f'Hot: {summary["hot_system_count"]} | '
        f'Active: {summary["active_system_count"]} | '
        f'Live Spike: {summary["live_spike_systems"]} | '
        f'Primary Threat: {summary["primary_threat"] or "None"}\n'
        f'Activity: {compact_activity(details)}'
    )

    guid_base = (
        f'{summary["route_id"]}|{summary["route_name"]}|{summary["route_temperature"]}|'
        f'{summary["risk_level"]}|{summary["total_score"]}|{summary["danger_density"]}|'
        f'{summary["hot_system_count"]}|{summary["active_system_count"]}|{summary["live_spike_systems"]}'
    )

    return {
        "title": title,
        "description": description,
        "guid": make_guid(guid_base),
    }


def build_rss(items: List[dict[str, str]], title: str, link: str, description: str) -> str:
    rss_items: List[str] = []

    for item in items:
        rss_items.append(
            f"""
    <item>
      <title>{escape(item["title"])}</title>
      <description>{escape(item["description"])}</description>
      <pubDate>{rfc2822_now()}</pubDate>
      <guid isPermaLink="false">{item["guid"]}</guid>
      <link>{escape(link)}</link>
    </item>""".rstrip()
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{escape(title)}</title>
    <link>{escape(link)}</link>
    <description>{escape(description)}</description>
    <lastBuildDate>{rfc2822_now()}</lastBuildDate>
    {''.join(rss_items)}
  </channel>
</rss>
"""


@app.get("/")
def root():
    return {
        "service": "PoddedProfits RSS",
        "feeds": [
            "/rss/trade-routes.xml",
        ],
    }


@app.get("/rss/trade-routes.xml")
def trade_routes():
    try:
        summary_rows, detail_rows = get_trade_route_data()
        detail_map = build_detail_map(detail_rows)

        items: List[dict[str, str]] = []
        for summary in summary_rows:
            details = detail_map.get(summary["route_id"], [])
            items.append(summarize_route(summary, details))

        xml = build_rss(
            items=items,
            title="PoddedProfits Trade Routes",
            link="https://feeds.poddedprofits.com/rss/trade-routes.xml",
            description="Live EVE trade route risk and activity feed",
        )
        return Response(content=xml, media_type="application/xml")

    except Exception as e:
        error_xml = build_rss(
            items=[{
                "title": "Trade Routes Feed Error",
                "description": f"Feed generation failed: {str(e)}",
                "guid": make_guid(f"error-{str(e)}"),
            }],
            title="PoddedProfits Trade Routes",
            link="https://feeds.poddedprofits.com/rss/trade-routes.xml",
            description="Live EVE trade route risk and activity feed",
        )
        return Response(content=error_xml, media_type="application/xml", status_code=500)