# hotshelf

Tiered media storage for Jellyfin. Keeps what the household is actually
watching on NVMe; everything else stays on HDD. All apps see one library
through a mergerfs union, so files move between tiers invisibly.

## Requirements

- Jellyfin, media library on a slow pool (e.g. `/data/media`)
- A fast filesystem for the cache (e.g. ZFS on NVMe)
- Docker with a reverse-proxy network (optional)

## Setup

1. Cache dataset:

```
zfs create -o quota=200G fast/media-cache
chown 1000:1000 /fast/media-cache
```

2. Move the library aside so the union can take its path
   (stop containers that mount it first):

```
docker stop jellyfin sonarr radarr sabnzbd
zfs set mountpoint=/data/media-hdd media/media
mkdir /data/media
```

3. Union mount, `/etc/systemd/system/data-media.mount`:

```
[Unit]
Description=hotshelf media union
After=zfs-mount.service
Requires=zfs-mount.service

[Mount]
What=/fast/media-cache:/data/media-hdd
Where=/data/media
Type=fuse.mergerfs
Options=category.create=ff,moveonenospc=true,cache.files=off,dropcacheonclose=false,allow_other,use_ino

[Install]
WantedBy=multi-user.target
```

```
apt install mergerfs
systemctl daemon-reload
systemctl enable --now data-media.mount
docker start jellyfin sonarr radarr sabnzbd
```

Every media app must mount the union path, never a branch.
`category.create=ff` makes new downloads land on NVMe automatically.

4. App:

```
git clone git@github.com:m2key1/hotshelf.git /srv/hotshelf && cd /srv/hotshelf
mkdir config && cp config.example.yaml config/config.yaml
```

Set `jellyfin.api_key` (Jellyfin Dashboard > API Keys) in the config, check
the volume paths in `compose.example.yaml`, then:

```
docker compose -f compose.example.yaml up -d --build
```

5. First run: open the web UI, press Run now, review Plan and Log.
   Dry-run is on by default and only logs. Disable it from the header
   once the plan looks right.

## Integrations

Jellyfin webhook (stages next episodes mid-watch, counts cache hits):
Webhook plugin > Generic Destination > url
`http://hotshelf:8080/webhook/jellyfin`, Playback Start only,
Send All Properties.

Prometheus:

```yaml
- job_name: hotshelf
  static_configs:
    - targets: ["hotshelf:8080"]
```

Homepage widget:

```yaml
- Cache:
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

## Rollback

Press Flush cache (moves everything back to HDD), stop the app, repoint the
containers to `/data/media-hdd`, disable the mount unit, rename the
mountpoint back.

## Tests

```
python -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/pytest
```
