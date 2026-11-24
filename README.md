# easyvm-redoxos

Walkthroughs and CI for **Redox OS** guests, driven by
[`easydev-org/easyvm`](https://github.com/easydev-org/easyvm).

## What lives here

`redox/steps/smoke.walk` - the only walk this repository has, and deliberately so: there is no
`install.walk`, because Redox cannot be installed by driving its installer (see below).
`scripts/assemble-redox-disk.py` builds the installed disk instead.

## What makes this guest different

### The installed disk is assembled, not installed

MEASURED on the pod, three times, on a freshly created 20 GiB AHCI disk: Redox's GUI installer (run
under `sudo`, which it needs or it reports "no drives found") writes a correct GPT and the EFI loader
and then stops after the first payload file:

```
Installing to RedoxFS partition with size 0x4ffcffe00
Loading filesystem.toml
Loading package files
Configuring system
Create file file:redox_installer_75:/usr/lib/init.d/00_base
<prompt returns, no error, no further output>
```

because the payload is FETCHED, not packaged: `installer/src/installer.rs` builds
`Library::new_remote("https://static.redox-os.org/pkg")` when it has no cookbook, and the live image
ships no local repository - `/pkg` holds 47 `*.pkg.tar.gz_head` metadata files and no `/pkg/repo`. A
`qemu-img convert` of its output showed 1 MiB of non-zero content in a 20 GiB image and an entirely
zero REDOX partition.

**The published ISO is already a bootable GPT disk.** Its own partitions are the layout a disk needs:

| partition | sectors | contents |
|---|---|---|
| BIOS | 34..2047 | |
| EFI | 2048..4095 | 1 MiB FAT12 holding `EFI/BOOT/BOOTX64.EFI` |
| REDOX | 4096..1177599 | a complete RedoxFS volume (version 6) |

so installing is copying those three pieces into a larger image.
`scripts/assemble-redox-disk.py` does that on the runner - no guest, no qemu boot, no packages - and
the assembled disk boots to the Orbital login form and logs in.

Three details decide whether it boots, each found by the failure it caused:

1. **A protective MBR at LBA 0.** With LBA 0 all zero the firmware never looks at the GPT, and the
   console says `BdsDxe: failed to load Boot0002 "UEFI QEMU HARDDISK QM00013" : Not Found`.
2. **The entry table at LBA 2.** Writing it into the ESP's and REDOX's first sectors leaves a valid
   header and every partition entry zero.
3. **REDOX at LBA 4096.** Redox's loader reads `device.partition_offset / BLOCK_SIZE` with
   `partition_offset` hardcoded to 2 MiB for a whole-disk handle
   (`bootloader/src/os/uefi/device.rs`, still `TODO: get block from partition table`), so a larger
   ESP pushes REDOX somewhere the loader never looks.

And the payload must be the ISO's, not one copied out of the running guest: `sudo dd if=/scheme/
disk.live/0` copies at 206 MB/s and looks right, but the result fails RedoxFS's block hashes
(`ERROR - READ_BLOCK: INCORRECT HASH ... for block 0x222B0`).

### The machine needs an AHCI disk and SLIRP networking

Redox's virtio-blk shows up as an EMPTY directory under `/scheme`, while an AHCI disk is a working
device node - the installer reports "no drives found" with one and lists the drive with the other.

Its `/etc/net` ships QEMU's user-mode addresses (`10.0.2.15`, router `10.0.2.2`), so a tap-bridged
guest comes up with no route at all. With `-netdev user` the same guest answers `ping 10.0.2.2` in
9 ms and `curl -sI https://static.redox-os.org/pkg/` with HTTP/2 200.

### The image is published ZSTD compressed

Redox publishes `.iso.zst` and nothing else, so `artifacts-publish.yml` decompresses it before packing
the tar. A walkthrough cannot do that, because decompression is preparation.

## The pipeline

```sh
gh workflow run artifacts-publish.yml -f which=iso-redox-0.9.0-desktop
gh workflow run artifacts-publish.yml -f which=disk-redox-0.9.0-desktop   # assembles the disk
gh workflow run redox-0.9.0-install.yml                                   # re-tags it redox-install
gh workflow run redox-0.9.0-smoke.yml
```

`disk-redox-0.9.0-desktop` is a fact about the IMAGE and `redox-install` is what this repository's
install produces; the smoke stage pulls the second, like every other guest here.

A disk tag carries a **qcow2**, not a tar around one - `stage.yml` fetches a disk tag straight onto
`work/disk.qcow2` and pushes it with `media-type: application/vnd.easydev.qcow2`.

## What lives elsewhere, on purpose

The **engine** and the **CI machinery** are both in `easydev-org/easyvm`; these workflows call
`easydev-org/easyvm/.github/workflows/stage.yml@v0.0.3-dev` for the second.

Disks pull from and publish to this repository's own ghcr package, `easydev-org/easyvm-redoxos`.