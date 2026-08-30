# Host setup (one-time, on the media host)

## 1. Cache dataset

```
zfs create -o quota=200G fast/media-cache
chown 1000:1000 /fast/media-cache
```

Quota is the hard backstop; the app budget stays below it.

## 2. Rename the slow branch

The current library moves aside so the union can take its path:

```
zfs set mountpoint=/data/media-slow media/media
```

## 3. mergerfs union

```
apt install mergerfs
```

`/etc/systemd/system/data-media.mount`:

```
[Unit]
Description=hotshelf media union
After=zfs-mount.service
Requires=zfs-mount.service

[Mount]
What=/fast/media-cache:/data/media-slow
Where=/data/media
Type=fuse.mergerfs
Options=category.create=ff,cache.files=off,dropcacheonclose=false,allow_other,use_ino

[Install]
WantedBy=multi-user.target
```

`category.create=ff` makes new imports land on the fast branch first.

## 4. Repoint containers

Jellyfin, Sonarr, Radarr and sabnzbd must all mount `/data/media` (the
union). Nothing may mount a branch path directly except hotshelf itself.
Jellyfin can mount it read-only.

## 5. Rollback

Stop hotshelf, press the demote-everything path (set budget to 0 and run),
repoint the containers back to `/data/media-slow`, disable the mount unit,
rename the mountpoint back.
