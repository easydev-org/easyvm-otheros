# easyvm-redoxos

Walkthroughs and CI for **Redox OS** guests, driven by
[`easydev-org/easyvm`](https://github.com/easydev-org/easyvm).

## What lives here

`redox/steps/` - the `.walk` files for `install` and `smoke`, plus the reference images they
compare against. The other stages (`ssh`, `vm-configure`) are added once an install produces a disk
that boots.

## What makes this guest different

Redox IS A MICROKERNEL OPERATING SYSTEM WRITTEN IN RUST, and its image is published ZSTD
COMPRESSED - `.iso.zst`, not `.iso`. That is the file this repository mirrors, so a stage that boots it
has to decompress it first; a walkthrough cannot, because decompression is preparation and preparation
belongs to the pipeline.

## The media is mirrored, not fetched from upstream

A stage pulls its installer image from this repository's ghcr package, never from the publisher:
`artifacts-publish.yml` downloads `iso-redox-0.9.0-desktop`, checks its digest, packs it into a tar and pushes one
tag. Every stage afterwards asks the package.

```sh
gh workflow run artifacts-publish.yml -f which=iso-redox-0.9.0-desktop
gh workflow run redox-0.9.0-install.yml
gh workflow run redox-0.9.0-smoke.yml
```

## What lives elsewhere, on purpose

The **engine** and the **CI machinery** are both in `easydev-org/easyvm`; these workflows call
`easydev-org/easyvm/.github/workflows/stage.yml@v0.0.3-dev` for the second.

Disks pull from and publish to this repository's own ghcr package, `easydev-org/easyvm-redoxos`.
