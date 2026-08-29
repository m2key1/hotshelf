from prometheus_client import Counter, Gauge

cache_bytes = Gauge("hotshelf_cache_bytes", "Bytes currently on the NVMe branch")
budget_bytes = Gauge("hotshelf_budget_bytes", "Configured cache budget in bytes")
hot_items = Gauge("hotshelf_hot_items", "Files currently on the NVMe branch")
dry_run = Gauge("hotshelf_dry_run", "1 while dry-run mode is active")
last_run = Gauge("hotshelf_last_run_timestamp", "Unix time of the last policy run")
promotes = Counter("hotshelf_promotes_total", "Files promoted to NVMe")
demotes = Counter("hotshelf_demotes_total", "Files demoted to HDD")
moved_bytes = Counter("hotshelf_moved_bytes_total", "Bytes moved in either direction")
errors = Counter("hotshelf_errors_total", "Failed moves")
cache_hits = Counter("hotshelf_cache_hits_total", "Playback starts served from NVMe")
cache_misses = Counter("hotshelf_cache_misses_total", "Playback starts served from HDD")
