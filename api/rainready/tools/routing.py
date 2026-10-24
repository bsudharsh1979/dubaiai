"""Constrained routing on the small seeded road graph (Dijkstra).

Links whose status is ``flooded`` or ``closed`` are excluded.  ``unknown`` links are
excluded too unless ``allow_unknown`` is set, and the result is then marked
"coverage insufficient".  Every returned path is labelled
"candidate route — requires verification"; if no path exists the tool returns
"no verified route" instead of guessing.
"""
from __future__ import annotations

import heapq

TOOL_VERSION = "constrained_router/0.2.0"


def shortest_path(links: list[dict], start_node: str, end_node: str, allow_unknown: bool = False) -> dict:
    adj: dict[str, list[tuple[str, float, str]]] = {}
    excluded = []
    unknown_used = False
    for l in links:
        st = l.get("status", "open")
        if st in {"flooded", "closed"}:
            excluded.append({"link_id": l["id"], "reason": st})
            continue
        if st == "unknown" and not allow_unknown:
            excluded.append({"link_id": l["id"], "reason": "status unknown (coverage gap)"})
            continue
        adj.setdefault(l["from_node"], []).append((l["to_node"], l["length_m"], l["id"]))
        adj.setdefault(l["to_node"], []).append((l["from_node"], l["length_m"], l["id"]))
    dist = {start_node: 0.0}
    prev: dict[str, tuple[str, str]] = {}
    pq = [(0.0, start_node)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == end_node:
            break
        if d > dist.get(u, float("inf")):
            continue
        for v, w, lid in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, lid)
                heapq.heappush(pq, (nd, v))
    if end_node not in dist:
        return {"tool_version": TOOL_VERSION, "status": "no verified route", "path_links": [], "length_m": None, "excluded_links": excluded,
                "reason": "no path avoiding flooded/closed/unknown links" if not allow_unknown else "no path even including unknown-status links"}
    path, node = [], end_node
    while node != start_node:
        u, lid = prev[node]
        path.append(lid)
        node = u
    path.reverse()
    status_by_id = {l["id"]: l.get("status", "open") for l in links}
    unknown_used = any(status_by_id[p] == "unknown" for p in path)
    return {"tool_version": TOOL_VERSION, "status": "candidate route — requires verification", "path_links": path,
            "length_m": round(dist[end_node], 1), "excluded_links": excluded,
            "coverage": "insufficient — includes unknown-status links" if unknown_used else "adequate for seeded graph",
            "caveat": "Not a safe-route determination; field verification required before use."}
