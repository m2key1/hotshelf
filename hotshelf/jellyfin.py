from datetime import datetime, timedelta, timezone

import httpx


class Jellyfin:
    """Thin client for the Jellyfin endpoints hotshelf needs."""

    def __init__(self, url, api_key, union_prefix):
        self.union_prefix = union_prefix.rstrip("/")
        self.client = httpx.Client(
            base_url=url, headers={"X-Emby-Token": api_key}, timeout=30
        )

    def get(self, path, **params):
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def relpath(self, path):
        """Map a Jellyfin item path to a branch-relative path, or None."""
        if path and path.startswith(self.union_prefix + "/"):
            return path[len(self.union_prefix) + 1:]
        return None

    def users(self, allowed_names):
        users = self.get("/Users")
        if allowed_names:
            users = [u for u in users if u["Name"] in allowed_names]
        return [(u["Id"], u["Name"]) for u in users]

    def resume(self, user_id):
        """In-progress items for a user as (relpath, size, last_played) tuples."""
        items = self.get(
            f"/Users/{user_id}/Items/Resume",
            Recursive="true", MediaTypes="Video",
            Fields="Path,MediaSources,UserData", Limit=100,
        ).get("Items", [])
        out = []
        for item in items:
            rp = self.relpath(item.get("Path"))
            if rp:
                played = (item.get("UserData") or {}).get("LastPlayedDate", "")
                out.append((rp, _size(item), played))
        return out

    def played_series(self, user_id, window_days):
        """Series the user played within the window: id -> (name, last_played)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        items = self.get(
            f"/Users/{user_id}/Items",
            Recursive="true", IncludeItemTypes="Episode", Filters="IsPlayed",
            SortBy="DatePlayed", SortOrder="Descending",
            Fields="SeriesId", Limit=300,
        ).get("Items", [])
        series = {}
        for item in items:
            played = (item.get("UserData") or {}).get("LastPlayedDate", "")
            sid = item.get("SeriesId")
            if not sid or not played or played < cutoff:
                continue
            if sid not in series or played > series[sid][1]:
                series[sid] = (item.get("SeriesName", sid), played)
        return series

    def item_path(self, item_id):
        """Branch-relative path of one item by id, or None."""
        items = self.get("/Items", ids=item_id, Fields="Path").get("Items", [])
        return self.relpath(items[0].get("Path")) if items else None

    def episodes(self, series_id, user_id):
        """Ordered episodes of a series with per-user watch state."""
        items = self.get(
            f"/Shows/{series_id}/Episodes",
            userId=user_id, Fields="Path,MediaSources", Limit=1000,
        ).get("Items", [])
        out = []
        for item in items:
            rp = self.relpath(item.get("Path"))
            if not rp:
                continue
            userdata = item.get("UserData") or {}
            out.append({
                "id": item["Id"],
                "relpath": rp,
                "size": _size(item),
                "season": item.get("ParentIndexNumber") or 0,
                "played": bool(userdata.get("Played")),
                "last_played": userdata.get("LastPlayedDate", ""),
            })
        return out


def _size(item):
    """Media file size reported by Jellyfin, 0 if unknown."""
    sources = item.get("MediaSources") or []
    return (sources[0].get("Size") or 0) if sources else 0
