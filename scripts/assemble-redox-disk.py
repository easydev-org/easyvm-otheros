"""assemble-redox-disk.py - build a bootable Redox disk from the published ISO.

THE "INSTALL" IS AN ASSEMBLY, NOT A BOOT. MEASURED on the pod: the Redox GUI installer, run under
sudo, writes a correct GPT and the EFI loader and then stops after the first payload file -

	Installing to RedoxFS partition with size 0x4ffcffe00
	Loading filesystem.toml
	Loading package files
	Configuring system
	Create file file:redox_installer_75:/usr/lib/init.d/00_base
	<prompt returns, no error, no further output>

- because the payload is FETCHED, not packaged: installer/src/installer.rs builds
`Library::new_remote("https://static.redox-os.org/pkg")` when it has no cookbook, and this live image
ships no local repository (/pkg holds 47 `*.pkg.tar.gz_head` metadata files and no /pkg/repo). A
qemu-img convert of its result shows 1 MiB of non-zero content in a 20 GiB image and an entirely zero
REDOX partition.

THE ISO IS ALREADY A BOOTABLE DISK. Its own GPT is the layout a disk needs - `EFI PART` at LBA 1, and

	part0 BIOS   34..2047
	part1 EFI    2048..4095      1 MiB FAT12 holding EFI/BOOT/BOOTX64.EFI
	part2 REDOX  4096..1177599   a complete RedoxFS volume (version 6, /bin, ion, initfs, orbital)

so building a disk is: that same GPT, that same EFI partition, and that same RedoxFS payload at LBA
4096. No guest, no qemu, no packages. MEASURED to work - the assembled disk boots to the Orbital login
form and logs in to the desktop.

THE THREE THINGS THAT DECIDE WHETHER IT BOOTS, each found by the failure it caused:

  1. THE PROTECTIVE MBR AT LBA 0. Without it the firmware never looks at the GPT. LBA 0 was all zero
     and mtools was happy, while the console said
         BdsDxe: failed to load Boot0002 "UEFI QEMU HARDDISK QM00013" : Not Found
     With a 0xEE entry covering LBA 1..end the loader runs: `Redox OS Bootloader 1.0.0 on x86_64/UEFI`.

  2. THE ENTRY TABLE AT LBA 2. It was being written into the ESP's and REDOX's first sectors, so the
     header was valid and every partition entry decoded as zero.

  3. REDOX AT LBA 4096. The loader's scan reads `device.partition_offset / BLOCK_SIZE` with
     `partition_offset` hardcoded to `2 * MIBI` for a whole-disk handle
     (bootloader/src/os/uefi/device.rs, still `TODO: get block from partition table`). A 32 MiB ESP
     pushed REDOX to LBA 67584 and the loader read the wrong place.

AND THE VOLUME MUST BE THE ISO'S, NOT ONE COPIED OUT OF THE RUNNING GUEST: `sudo dd if=/scheme/
disk.live/0` copies at 206 MB/s and looks right, but the result fails RedoxFS's block hashes -

	ERROR - READ_BLOCK: INCORRECT HASH ... for block 0x222B0
	WARN - No RedoxFS partitions found
	SETUP PANIC: Failed to open RedoxFS: No such file or directory

- the guest's device node can return a short block and the loader only retries 25 times.

usage: assemble-redox-disk.py <iso> <out.qcow2> [size-gb]
"""
import os
import struct
import subprocess
import sys
import uuid
import zlib

SECTOR = 512
MIB = 1024 * 1024

ESP_START = 2048      # lba: the ISO's own EFI extent
ESP_SECTORS = 2048    # 1 MiB
REDOX_START = 4096    # lba = 2 MiB, the offset the loader hardcodes

BIOS_TYPE = uuid.UUID("21686148-6449-6E6F-744E-656564454649").bytes_le
EFI_TYPE = uuid.UUID("C12A7328-F81F-11D2-BA4B-00A0C93EC93B").bytes_le
LINUX_TYPE = uuid.UUID("0FC63DAF-8483-4772-8E79-3D69D8477DE4").bytes_le


def gpt_entry(type_guid, first, last, name, part_guid, attrs=0):
    e = bytearray(128)
    e[0:16] = type_guid
    e[16:32] = part_guid
    struct.pack_into("<QQQ", e, 32, first, last, attrs)
    nm = name.encode("utf-16-le")[:72]
    e[56:56 + len(nm)] = nm
    return bytes(e)


def main():
    src, out = sys.argv[1], sys.argv[2]
    size_gb = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    # THE ISO IS PEEKED AT, NOT READ WHOLE. It is 576 MiB and only two slices of it are needed; a
    # `read()` of the lot is another 576 MiB a job with 7 GiB cannot always spare.
    iso_file = open(src, "rb")
    iso_size = os.fstat(iso_file.fileno()).st_size
    print("iso: %d bytes" % iso_size)

    def read_at(offset, length):
        iso_file.seek(offset)
        got = iso_file.read(length)
        if len(got) != length:
            sys.exit("the ISO is %d bytes; wanted %d at offset %d" % (iso_size, length, offset))
        return got

    # THE ESP, VERBATIM. Its boot sector ends 55 aa, which is the one check that says this is the FAT
    # volume and not some other slice of the ISO.
    esp = read_at(ESP_START * SECTOR, ESP_SECTORS * SECTOR)
    if esp[510:512] != b"\x55\xaa":
        sys.exit("the ISO's EFI partition at lba %d is not a FAT volume: %r"
                 % (ESP_START, esp[510:512]))

    # THE PAYLOAD'S EXTENT COMES FROM THE ISO'S OWN GPT, so a different release needs no number here.
    hdr = read_at(512, 92)
    if hdr[:8] != b"EFI PART":
        sys.exit("the ISO is not a GPT disk")
    iso_alt = struct.unpack_from("<Q", hdr, 32)[0]
    redox_sectors = iso_alt - 33 - REDOX_START + 1
    print("redoxfs: %d bytes from the ISO" % (redox_sectors * SECTOR))

    total = size_gb * 1024
    total_sectors = total * 2048

    parts = [
        (BIOS_TYPE, 34, 2047, "BIOS", 0),
        (EFI_TYPE, ESP_START, ESP_START + ESP_SECTORS - 1, "EFI", 0),
        (LINUX_TYPE, REDOX_START, total_sectors - 34, "REDOX", 0),
    ]
    entries = b""
    for i, (t, f, l, nm, at) in enumerate(parts):
        pg = uuid.uuid5(uuid.NAMESPACE_OID, "redox-part-%d" % i).bytes_le
        entries += gpt_entry(t, f, l, nm, pg, at)
    entries += b"\x00" * (128 * 128 - len(entries))

    header = bytearray(92)
    header[0:8] = b"EFI PART"
    struct.pack_into("<I", header, 8, 0x00010000)
    struct.pack_into("<I", header, 12, 92)
    struct.pack_into("<Q", header, 24, 1)
    struct.pack_into("<Q", header, 32, total_sectors - 1)
    struct.pack_into("<Q", header, 40, 34)
    struct.pack_into("<Q", header, 48, total_sectors - 34)
    header[56:72] = uuid.uuid5(uuid.NAMESPACE_OID, "redox-disk").bytes_le
    struct.pack_into("<Q", header, 72, 2)
    struct.pack_into("<I", header, 80, 128)
    struct.pack_into("<I", header, 84, 128)
    struct.pack_into("<I", header, 88, zlib.crc32(entries) & 0xFFFFFFFF)
    struct.pack_into("<I", header, 16, zlib.crc32(bytes(header)) & 0xFFFFFFFF)

    # THE IMAGE IS STREAMED, NOT BUILT IN MEMORY.
    #
    # MEASURED on the first CI run: a `bytearray(total * MIB)` for 20 GiB raised `MemoryError` at
    # line 137 on a GitHub runner, whose job has about 7 GiB. Nothing about this disk needs the whole
    # image resident - it is a GPT, two small structures at fixed offsets, and one 573 MiB payload -
    # so the qcow2 is created first and every piece is written into it at its own offset.
    subprocess.run(["qemu-img", "create", "-f", "qcow2", out, "%dM" % (total)], check=True)

    def write_at(path, offset, data):
        """Write `data` at `offset` of the image, through qemu-io so a qcow2 is edited in place.

        THE FORM IS `write -s <file> <offset> <length>`, and the first attempt got it wrong as
        `write -<offset> <length> <file>`, which qemu-io answered with exit 1 and no message -
        MEASURED: the image stayed a bare 193K header and the script reported a CalledProcessError
        naming an argument list rather than a mistake.
        """
        with open(tmp_piece, "wb") as f:
            f.write(data)
        subprocess.run(["qemu-io", "-f", "qcow2", "-c",
                        "write -s %s %d %d" % (tmp_piece, offset, len(data)), path],
                       check=True, stdout=subprocess.DEVNULL)

    tmp_piece = out + ".piece"

    # 1. THE PROTECTIVE MBR. UEFI uses this 0xEE entry to decide the disk holds a GPT at all; with
    #    LBA 0 all zero the firmware never reads the header at LBA 1.
    pmbr = bytearray(SECTOR)
    pmbr[446 + 1:446 + 4] = b"\x00\x02\x00"
    pmbr[446 + 4] = 0xEE
    pmbr[446 + 5:446 + 8] = b"\xff\xff\xff"
    struct.pack_into("<I", pmbr, 446 + 8, 1)
    struct.pack_into("<I", pmbr, 446 + 12, min(total_sectors - 1, 0xFFFFFFFF))
    pmbr[510:512] = b"\x55\xaa"
    write_at(out, 0, bytes(pmbr))

    # 2. THE HEADER AND THE ENTRY TABLE, EACH AT THE LBA ITS OWN FIELD NAMES.
    write_at(out, 1 * SECTOR, bytes(header))
    write_at(out, 2 * SECTOR, entries)

    # 3. THE BACKUP HEADER AND ITS TABLE, POINTING BACK THE OTHER WAY.
    backup = bytearray(header)
    struct.pack_into("<Q", backup, 24, total_sectors - 1)
    struct.pack_into("<Q", backup, 32, 1)
    struct.pack_into("<Q", backup, 72, total_sectors - 33)
    struct.pack_into("<I", backup, 16, 0)
    struct.pack_into("<I", backup, 16, zlib.crc32(bytes(backup)) & 0xFFFFFFFF)
    write_at(out, (total_sectors - 1) * SECTOR, bytes(backup))
    write_at(out, (total_sectors - 33) * SECTOR, entries)

    # 4. THE TWO PAYLOAD PARTITIONS, BOTH COPIED FROM THE ISO. The 573 MiB payload is written in
    #    chunks so a larger medium would not need more memory either.
    write_at(out, ESP_START * SECTOR, esp)
    chunk = 32 * MIB
    total_payload = redox_sectors * SECTOR
    for i in range(0, total_payload, chunk):
        piece = read_at(REDOX_START * SECTOR + i, min(chunk, total_payload - i))
        write_at(out, REDOX_START * SECTOR + i, piece)
    # THE PAYLOAD'S IDENTITY IS CHECKED AT ITS FIRST BYTES, after it has been copied, so the check
    # cannot pass on a slice that was never written.
    head = read_at(REDOX_START * SECTOR, 8)
    print("iso payload sig: %r" % head)
    if head != b"RedoxFS\x00":
        sys.exit("the ISO's REDOX partition is not RedoxFS: %r" % head)
    print("esp at lba %d, redoxfs at lba %d" % (ESP_START, REDOX_START))

    os.unlink(tmp_piece)

    # THE RESULT IS COMPACTED, because qemu-io writes every touched cluster and the payload's zero
    # runs would otherwise be stored. A convert to a new qcow2 is what drops them.
    compact = out + ".compact"
    subprocess.run(["qemu-img", "convert", "-f", "qcow2", "-O", "qcow2", "-c", out, compact],
                   check=True)
    os.replace(compact, out)
    print("wrote", out)


if __name__ == "__main__":
    main()