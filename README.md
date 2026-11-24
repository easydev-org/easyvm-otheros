# easyvm-otheros

Walkthroughs and CI for operating systems that are not Linux, Windows, macOS, BSD or Android - today
**Haiku**, **Redox OS**, **Debian GNU/Hurd**, **ToaruOS**, **Sculpt OS**, **ReactOS**,
**KolibriOS** and **AROS** - driven by
[`easydev-org/easyvm`](https://github.com/easydev-org/easyvm).

## What lives here

Eight guests, in two groups, and which group a guest is in is a finding rather than a preference.

**Two have a real `install.walk`** - an installer that partitions a disk, copies a system and writes a
boot sector, driven step by step:

```
haiku/steps/install.walk      41 steps   DriveSetup: Intel map, BFS, then the Installer
haiku/steps/smoke.walk         3 steps   boot the published disk, read the deskbar
reactos/steps/install.walk    28 steps   the Setup Wizard, driven entirely by keyboard
reactos/steps/smoke.walk       3 steps   boot the published disk, read the desktop
```

**Six publish a smoke walk only**, and each for its own measured reason:

| guest | why there is no `install.walk` |
| --- | --- |
| Redox OS | its installer fetches packages over a network the live image has no repository for, so `scripts/assemble-redox-disk.py` builds a disk from the ISO's own partitions |
| Debian GNU/Hurd | Debian publishes a **finished disk image**; there is nothing to install |
| ToaruOS | one 7 MiB hybrid live image, no persistence, nothing to install |
| Sculpt OS | a 41 MiB whole-disk image with its own GPT and boot loader |
| KolibriOS | a 99 MiB LiveCD that boots to a desktop in RAM; no installer, no persistence |
| AROS | a 455 MiB live `boot-iso` for the AmigaOS 3.1 API; it carries an installer, but the claim here is that the system comes up |

`scripts/assemble-redox-disk.py` is what the `assemble` job in `artifacts-publish.yml` runs.

## Haiku

Haiku R1/beta5 is installed by driving its own installer, and the disk it publishes boots on **BIOS**.

```
haiku/steps/install.walk    SeaBIOS + the anyboot ISO -> a 20 GiB disk with a BFS
haiku/steps/smoke.walk      boot that disk with no ISO attached and read the deskbar
```

The medium is `haiku-r1beta5-x86_64-anyboot.iso`, 1,477,246,976 bytes, sha256
`22ae312a38e98083718b6984186e753d15806bd6ea44542144fdcef42c4dcb69` - the digest on haiku-os.org's own
download page.

### Why BIOS, and why the partition map is the whole story

r1beta5's installer writes an **MBR boot sector and a Be File System**, and it does **not** create an
ESP. An installed disk therefore boots through `bios_ia32/stage1` and only through it, unless somebody
also runs `Tools -> Install EFI loader` against a hand-made FAT32 partition. The walk takes the first
path, which is what the medium itself carries: the anyboot ISO's own `part0` is `type=0xeb`.

That makes one menu item in DriveSetup decisive:

```
Disk -> Initialize -> Intel Partition Map...     <- the SECOND entry
Disk -> Initialize -> GUID Partition Map...      <- the FIRST
```

MEASURED, and this cost two whole installs: choosing GUID produces a disk that reaches 753 MiB with
the installer reporting `Installation completed. Boot sector has been written to 'Haiku'.`, and SeaBIOS
then prints `No bootable device` - because the protective MBR at LBA 0 describes a GPT and never an
active `0xEB` partition. The Intel map produces

```
part0 type=0xeb active=128 lba=64 cnt=41940992
```

which is what stage1 reads.

### The shutdown is a power button, not a kill

MEASURED: `stop kill` publishes a disk whose BFS root directory holds only `.` and `..`. The journal
was never replayed, so stage1 walks the directory, does not find `system/packages/haiku_loader`, and
prints `bios_ia32 stage1: Failed to load OS`. Pressing the guest's power button (`acpi power`) and
waiting for the process to go (`wait_until stopped`) lets BFS commit, and the same disk boots to the
desktop.

### 1920x1080 is the firmware, not a choice

With `vgamem_mb=32`, SeaBIOS hands Haiku's VESA driver a mode table and the driver settles on
**1920x1080**; OVMF's GOP on the same card takes the largest mode that fits and lands on
**3840x2160**. So the BIOS walk's coordinates are at their natural scale, and a UEFI variant of these
files would need every one of them doubled.

### The OCR reads the dialog's body, not its title

`Welcome to Haiku!` is drawn in a yellow title tab and tesseract **drops it entirely** from the
welcome dialog's crop - the reading starts at `Esperanto` and runs on through `Thank you for trying
out Haiku!`. A `words: [[welcome]]` gate therefore never fires. The walk waits on `thank`, `trying`
and `haiku`, which are plain words on a white background.

## ToaruOS

ToaruOS 2.3.2 ships as a single 7.2 MiB live image and needs no installation at all - its own release
notes describe it as a "live CD" with an in-memory read-write filesystem and no persistence between
boots. So this repository publishes the medium and one smoke walk:

```
toaru/steps/smoke.walk    attach the image as a CD, read the tutorial window, record the desktop
```

The image is **hybrid**: LBA 0 holds a boot sector and offset 32769 holds the ISO9660 catalog
(`CD001`), so the same file boots from a CD. That is what the project recommends:

```sh
qemu-system-x86_64 -cdrom image.iso -m 1G -device AC97 -enable-kvm
```

MEASURED, and the failures are worth recording because each one looks like "ToaruOS does not boot":

| attachment | result |
|---|---|
| `-device floppy` | qemu exits before its QMP socket - a `floppy` needs an `isa-fdc` controller q35 does not carry |
| `-drive file=toaru.iso,if=ide` (hard disk) | the firmware finds no El Torito catalog and falls through to iPXE, then `No bootable device` |
| `media=cdrom` on `ahci.1` | boots to the desktop |

The desktop is the ToaruOS menubar (`Applications`, `Welcome to ToaruOS!`) and a tutorial window; the
walk reads for `toaruos`, a word no boot banner produces.

## Sculpt OS

Sculpt OS 26.10 is Genode Labs' general-purpose OS - a custom microkernel, capability-based security,
sandboxed drivers and virtual machines. It is a **41 MiB whole-disk image** with its own GPT and boot
loader, so it too has no install leg:

```
sculpt/steps/smoke.walk    attach the image as a hard disk, read the Leitzentrale, record it
```

### Its desktop is the Leitzentrale, and that is not a taskbar

What Sculpt draws is a top strip with `Files`, `Components` and `System`, a live graph of running
components joined by wires (`platform`, `vesa fb`, `ps2`, `ahci`, `gui`, `pointer`, `leitzentrale`,
`font`, `report logger`, `clipboard`, `network`, `ram fs`), and a `Diagnostics` panel in the lower
left. There is no wallpaper desktop behind it - the administrative UI **is** the system's interface,
so a stage waiting for a window manager would wait for ever.

Genode's own QEMU line is what the walk uses:

```sh
qemu-system-x86_64 -display sdl -cpu Skylake-Client -machine q35 \
                   -m 1024 -drive format=raw,file=sculpt-26-10.img \
                   -netdev user,id=net0 -device e1000,netdev=net0
```

q35, **one** GiB of RAM, a raw image attached as a disk (not a CD), and an e1000 on user networking.
The engine fixes `-cpu Skylake-Client-v4`, a superset of the `Skylake-Client` the docs name.

### The gate reads the panel, not the frame

MEASURED: the whole 1024x768 frame enlarged three times reads the Leitzentrale as

```
see: 12 word(s): * seeuettte te Zz GENODE blueprint query requires depot ...
```

- `diagnostics` is not among the twelve words. The same frame cropped to the panel's own corner
(`rect [0, 660, 320, 740]` at `scale 3`) reads `Diagnostics` on every attempt. A small frame is not a
reason to read all of it; it is the reason to read less. `leitzentrale` is a small label inside the
graph and tesseract drops it entirely, so the gate names the one label in a fixed corner.

## ReactOS

ReactOS 0.4.16 is the second guest here with a real `install.walk` - its installer partitions a disk,
formats a FAT partition, copies a system and writes a boot sector:

```
reactos/steps/install.walk    drive the Setup Wizard by keyboard, publish the disk
reactos/steps/smoke.walk      boot that disk with no CD and read the desktop
```

### It is 32-bit, BIOS-only, and has no virtio-blk

Three facts that shape every argument in both files:

| | |
| --- | --- |
| **32-bit only** | the ISO is i386 and there is no amd64 ReactOS release |
| **BIOS only** | it boots from the MBR through SeaBIOS; there is no UEFI loader, so no pflash and no OVMF |
| **no virtio-blk** | the install disc ships no driver for it, so the target is `-drive if=ide` |

`-machine pc` is i440fx, which is what the project's own QEMU page names.

### Every action is a keystroke, because the guest picks 800x600

ReactOS fixes its own display mode - its "Setup the basic devices" page says
`VESA Display (800x600x32)` - and the engine **refuses a `click:` on any frame that is not
1920x1080**:

```
error: click (508, 447) is a coordinate measured at 1920x1080 but the framebuffer is 800x600.
       A click cannot be rescaled the way a reading can
```

MEASURED with `-device VGA,xres=1920,yres=1080,vgamem_mb=32`: the guest still draws 800x600, so the
frame cannot be talked up to the size a click needs. The wizard is fully keyboard-driven, so the walk
uses `input ret` / `input down` / `input spc` and no coordinates at all.

Two keyboard details cost real installs and are both in the file:

- the **language page needs `tab` before `return`** - its focus starts in the language listbox, so a
  bare Return goes to the list and the wizard never advances;
- the **second stage is one loop, not ten Returns** - "Welcome to the ReactOS Setup Wizard" is drawn by
  *both* stages, so a gate on it fires on the first stage, and the page body says "installs ReactOS on
  your **computer**", so a gate on `computer` matched while the wizard was still on screen. The loop
  presses Return and looks only for the desktop's own icon labels (`Recycle Bin` or `Documents`),
  which the wizard never prints.

### Installing it needs a hand-written job, because the engine will not publish a small disk

The walk itself is ordinary - it drives the wizard and stops the machine. What is not ordinary is the
publishing step:

A complete ReactOS 0.4.16 install is **415 MiB**, and the engine refuses to publish anything below
512 MiB. `easydev-org/easyvm#9` records it: `min_mb` is declared as a field of `stop:` and `disk:` so a
small artifact can say what small means, but nothing folds it into the `disk_min_mb` that `compress:`
reads, so the floor is always 512. `stage.yml` carries a second copy of the same check with no override.

So `reactos-0.4.16-install.yml` is a **hand-written job** rather than a `stage.yml` caller: it pulls the
medium, starts ONE daemon, runs the same `reactos/steps/install.walk`, and then pushes
`work/disk.qcow2` with `scripts/publish-disk.py`, which has no floor. Everything that matters is still
the engine's - the walk is unmodified and the machine is the qemu its own `boot:` step describes.

That script exists because two details are easy to get wrong and were both measured: the blob must be
the **qcow2 itself** (not a tar holding one, which is what `crane append` produces), and the manifest
must have **no space after the colons** - `pull-artifact.sh` reads it with
`sed 's/.*"digest":"\(sha256:[a-f0-9]*\)".*/\1/p'`, so Python's default `json.dumps` separators
produce a valid manifest that the script cannot read (run 45454429673: "the manifest for
reactos-install has no digest or size", about a tag that was there).

When #9 is fixed this file becomes a `stage.yml` caller with `out:`/`publish:`, the walk regains
`save "{{ out }}"`, and the push step is deleted. The tag is already `reactos-install`, so the smoke leg
needs no change either.

### The one bug that cost the most: qemu's write cache

MEASURED, and it looked like a dozen different problems before it was read properly. Every CI run
produced a disk of **exactly 314,507,264 bytes** against 415 MiB on the pod, and the smoke leg booted it
straight back into the second stage - or, on one run, into ReactOS's own dialog:

```
lisass.exe -Bad Image ... Try reinstalling the application using the ...
```

That is ReactOS reporting a DLL whose contents do not match what the loader expects: the files the
first stage wrote were not the files the second stage read back. ReactOS reboots ITSELF between the two
stages and qemu does not exit at that moment, so pages the guest had written could still be in qemu's
cache when the second stage read the same file back through it.

The fix is one argument - `cache=directsync` on the target - and the disk became 435,355,648 bytes,
booted to its desktop, and passed the smoke leg. It is the same property Haiku's install needed from a
clean shutdown: what the guest wrote is on the host file before the next stage reads it.

### Both legs are green in CI

```
reactos-0.4.16-install   28 steps   run 45496609390
reactos-0.4.16-smoke      3 steps   run 45498403340   "the desktop is up [until]: read \"documents\""
```

## KolibriOS

KolibriOS is a 32-bit OS written almost entirely in FASM assembly - the `FASM` icon on its own menu is
the assembler. It ships as a LiveCD that boots to a desktop in RAM: no installer, no login, no
persistence.

```
kolibri/steps/smoke.walk    attach the ISO as a CD on pc, compare the menu bar, record the desktop
```

MEASURED: the ISO boots under KVM to its full desktop in well under a minute - the icon grid down both
sides (`KFIFZ`, `EDITLE`, `KFAR`, `DEBUG`, `DBOARD`, `KPACK`, `DINO`, `CLICKS`, `TETRIS`, `SUDOKU`,
`GOMOKU`, `KOSILKA`, `PONG`, `SEAWAR`, `MINE`), the `Menu` bar along the bottom with its `En` language
badge and a clock, and a pixel-art wallpaper.

### The witness is a picture, and that is the point

KolibriOS's 8-pixel bitmap font defeats this OCR. MEASURED, the whole desktop reads as fragments:

```
kena
TuNveAD
ROSAVE
PIPES.
eOuITE
FeeREAD
```

- which is every icon **label**, mis-read. A `words:` gate could only be tuned to what one tesseract
version happened to hallucinate, and would break on the next.

A desktop is a thing you recognise by sight, so the gate compares sight: `mode: like` crops the same
rectangle from the live frame and from `reference/desktop.png` and scores them - **1.0000 similar** on
the second attempt. The rectangle is the menu bar's left end (the green `Menu` button and the blue icon
beside it), which never changes; the clock at the right end changes every minute and stays outside it.

The reference is a **full 1024x768 frame**, not a cropped bar: `similarityInRect` crops the reference
with the same `rect`, so a pre-cropped picture would be cut a second time and never match.

## AROS

AROS is an open-source reimplementation of the AmigaOS 3.1 API, and `pc-x86_64` is its native port for
ordinary PCs. The published `boot-iso` is a complete live system:

```
aros/steps/smoke.walk    attach the ISO as a CD on pc, compare the wordmark, record the desktop
```

MEASURED: it boots to Wanderer - `RAM Disk`, `AROS Live CD`, `InstallAROS`, `Network` and `Readme` down
the left, the `Wanderer` screen title along the top, the `aros` wordmark bottom-right.

The media does carry an installer (`InstallAROS`), and this repository deliberately does not drive it:
that would replace the RAM disk with a hard disk and answer a different question than "does this system
come up on our machine". A future `install.walk` would start from this file and click that icon.

### The witness is a picture, like KolibriOS

MEASURED, AROS's proportional bitmap font defeats this OCR - the whole desktop reads as `mem` and
`RAMIDIE:` - so the gate uses `mode: like` against `reference/desktop.png`, cropping the bottom-right
corner where the `aros` wordmark is drawn. **1.0000 similar** on the second attempt.

The reference is a full 1024x768 frame, because `similarityInRect` crops the reference with the same
`rect`.

## Debian GNU/Hurd

Debian publishes this guest two ways - an installer ISO and a pre-installed disk - and this repository
uses the **pre-installed disk**, which boots straight to a login prompt:

```
tty1
login: _
Debian GNU/Hurd forky/sid debian console
```

`root` and `demo` both log in **with no password**, which is the image's own README.

Its kernel answers:

```
root@debian:~# uname -a
GNU debian 0.9 GNU-Mach 1.8+git20260224-up-amd64/Hurd-0.9 x86_64 GNU
```

### The machine has no USB devices, and that is measured

**GNU Mach has almost no USB support.** Debian's own Hurd hardware page says so outright - "as of
January 2026, users should install the Hurd on physical machines with a CD, because the Hurd has
almost no USB support" - and the developers are still working on it through rumpusbdisk.

MEASURED here: a guest with `-device usb-kbd` received **nothing** (`login:` stayed empty while the
same keypresses reached a machine with only PS/2). A guest with **no `-device usb-*` at all** types
correctly, on **q35 as well as pc**, because both boards carry the i8042 controller Mach's inherited
driver expects. The walk therefore uses q35 like every other guest here and simply attaches no USB
input.

The disk is IDE: Mach's block drivers come from Linux 2.4 and cover IDE, and the image's own README
starts it with a bare `-drive file=debian-hurd*.img`.

### Its desktop is icewm, and it does not start itself

The image boots to a **text console**. `icewm`, `Xorg` and `startx` are all installed
(`/usr/bin/icewm`, `/usr/bin/Xorg`, `/usr/bin/startx`), and `startx` brings up icewm - MEASURED, with
the taskbar's workspace buttons and clock on screen.

The release notes name icewm as the default window manager of the **installer's task selection**,
which is not the same claim as "the image starts it". They also say GNOME and KDE "are not yet
completely installable and working", so a Hurd desktop is icewm.

### The desktop is recognised by comparing pictures, not by OCR

Three text witnesses failed on a desktop that was already up: `icewm` is drawn as a **logo**
tesseract refuses at every scale; the workspace buttons are plain text but the highlighted one
bleeds into its own beige block (`tesseract` read the row as `ey 2`); the clock is white-on-black at
12 px and returned nothing.

So `hurd/steps/smoke.walk` uses `mode like` against `hurd/steps/reference/desktop.png`, cropping the
same rectangle - `[0, 1010, 700, 1080]`, icewm's mark, its buttons and all four workspace tabs, with
the changing clock deliberately outside - from both pictures and scoring them. MEASURED across three
frames taken at different times: **1.0000** similarity each, because that part of the bar never
changes.

The reference is a **full 1920x1080 frame**, not a cropped bar: the engine crops the reference with
the same `rect` as the live frame, so a pre-cropped picture is cut twice and never matches.

And it cannot match the boot console: that frame is 720x400, so a rectangle reaching y=1080 is
outside it. The comparison only has an answer once `startx` switches the framebuffer to 1920x1080 -
which is the desktop arriving.

## Redox OS

### The installed disk is assembled, not installed

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

Every guest is two steps: publish the medium once, then run the stage that boots it. Two guests add a
third, because they install.

```sh
# the medium, once per release (this repository's own ghcr package)
gh workflow run artifacts-publish.yml -f which=iso-haiku-r1beta5
gh workflow run artifacts-publish.yml -f which=iso-toaruos-2.3.2
gh workflow run artifacts-publish.yml -f which=iso-kolibrios-0.7.7.0
gh workflow run artifacts-publish.yml -f which=iso-aros-202609
gh workflow run artifacts-publish.yml -f which=disk-sculpt-26.10
gh workflow run artifacts-publish.yml -f which=disk-hurd-20260314
gh workflow run artifacts-publish.yml -f which=iso-redox-0.9.0-desktop

# TWO MEDIUMS ARE NOT IN THAT JOB, AND NEITHER IS A MISSING LINE:
#
#   iso-reactos-0.4.16   SourceForge refuses a GitHub runner (403 on every retry, reproduced by hand
#                        with the download step's own user-agent and referer). It is published with
#                        scripts/publish-disk.py from the copy this repository verified.
#   iso-redox-0.9.0-desktop's DISK half, `disk-redox-0.9.0-desktop`, is built by that job's `assemble`
#                        stage from the ISO, not by a `publish` row.

# the stages, in the order each guest needs
gh workflow run haiku-r1beta5-install.yml      && gh workflow run haiku-r1beta5-smoke.yml
gh workflow run reactos-0.4.16-install.yml     && gh workflow run reactos-0.4.16-smoke.yml
gh workflow run redox-0.9.0-install.yml        && gh workflow run redox-0.9.0-smoke.yml
gh workflow run hurd-20260314-smoke.yml        # Debian publishes a finished disk
gh workflow run toaruos-2.3.2-smoke.yml
gh workflow run sculpt-26.10-smoke.yml
gh workflow run kolibrios-0.7.7.0-smoke.yml
gh workflow run aros-202609-smoke.yml
```

Which tag each stage consumes:

| guest | medium tag | disk tag | stage that runs |
| --- | --- | --- | --- |
| Haiku | `iso-haiku-r1beta5` | `haiku-install` | install -> smoke |
| ReactOS | `iso-reactos-0.4.16` | `reactos-install` | install -> smoke |
| Redox OS | `iso-redox-0.9.0-desktop` | `redox-install` | install -> smoke |
| Debian GNU/Hurd | - | `hurd-install` | smoke |
| ToaruOS | `iso-toaruos-2.3.2` | - | smoke |
| Sculpt OS | `disk-sculpt-26.10` | - | smoke |
| KolibriOS | `iso-kolibrios-0.7.7.0` | - | smoke |
| AROS | `iso-aros-202609` | - | smoke |

`disk-redox-0.9.0-desktop` is a fact about the IMAGE and `redox-install` is what this repository's
install produces; the smoke stage pulls the second, like every other guest here.

A disk tag carries a **qcow2**, not a tar around one - `stage.yml` fetches a disk tag straight onto
`work/disk.qcow2` and pushes it with `media-type: application/vnd.easydev.qcow2`. A medium tag carries a
**tar** holding the file the walk names, because `stage.yml` unpacks only when the destination ends in
`.tar`.

## What lives elsewhere, on purpose

The **engine** and the **CI machinery** are both in `easydev-org/easyvm`; these workflows call
`easydev-org/easyvm/.github/workflows/stage.yml@v0.0.3-dev` for the second.

Disks pull from and publish to this repository's own ghcr package, `easydev-org/easyvm-otheros`.