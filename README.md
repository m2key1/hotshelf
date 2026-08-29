# hotshelf

Tiered media storage for Jellyfin. Keeps what the household is actually
watching on NVMe; everything else lives on HDD. All apps see one library
through a mergerfs union, so files move between tiers invisibly.

See DESIGN.md for the architecture and docs/host-setup.md for the one-time
host preparation (union mount, cache dataset, volume repointing).

## Run

```
cp config.example.yaml config/config.yaml   # edit: jellyfin url + api key
docker compose -f compose.example.yaml up -d
```

Web UI on :8080 (status, plan preview, pins, config editor, activity log).
Dry-run is on by default: the first runs only log what they would move.
Disable it from the header once the plan looks right.

## Endpoints

- `/metrics` Prometheus
- `/api/homepage` JSON for a Homepage customapi widget
- `/webhook/jellyfin` POST target for the Jellyfin webhook plugin
  (PlaybackStart): counts a cache hit or miss, then triggers a debounced
  policy run so the next episodes stage mid-watch

## Wiring the integrations

Jellyfin webhook: install the Webhook plugin, add a Generic Destination with
url `http://hotshelf:8080/webhook/jellyfin`, enable only Playback Start and
the "Send All Properties" template.

Homepage widget:

```yaml
- Cache:
    icon: mdi-harddisk
    widget:
      type: customapi
      url: http://hotshelf:8080/api/homepage
      mappings:
        - field: used_gb
          label: hot
          suffix: " GB"
        - field: hot_items
          label: items
```

Prometheus scrape job:

```yaml
- job_name: hotshelf
  static_configs:
    - targets: ["hotshelf:8080"]
```

## Tests

```
python -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/pytest
```
