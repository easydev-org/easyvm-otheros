"""Publish one local disk file to ghcr under a tag, as a single-layer OCI artifact.

WHY THIS EXISTS, AND WHY IT IS A SCRIPT IN THIS REPOSITORY RATHER THAN A GENERATED COMMAND SOMEBODY
REMEMBERS.

A stage publishes the disk its walk produced, through `save:` / `compress:`. That path refuses any disk
below 512 MiB (easydev-org/easyvm#9): `min_mb` is declared as a field of `stop:` and of `disk:` so a
small artifact can say what small means, but nothing folds it into the `disk_min_mb` that `compress:`
reads, so the floor is always 512 and a walkthrough cannot lower it. stage.yml then carries a SECOND
copy of the same 512 MiB check with no override at all.

ReactOS 0.4.16 is such a guest: a complete install is 415 MiB. Its `reactos/steps/install.walk` runs
to the end and then cannot publish, so the disk the smoke leg pulls is published from here, once, by
hand. This script is that hand, written down - so the artifact is reproducible from the repository
rather than from somebody's shell history, and so the command that made it can be read and checked.

WHAT IT WRITES, AND THE ONE DETAIL THAT MATTERS:

  * ONE LAYER, whose blob IS the qcow2 - not a tar holding one. `pull-artifact.sh` downloads the blob
    by digest and writes it straight to `disk.qcow2`, which is what the redox `redox-install` leg does
    too. `crane append` is NOT used for this reason: it wraps the file in a tar layer.
  * A MANIFEST WITH NO SPACES AFTER THE COLONS. `pull-artifact.sh` reads the digest and size with
        sed -n 's/.*"digest":"\\(sha256:[a-f0-9]*\\)".*/\\1/p'
        sed -n 's/.*"size":\\([0-9]*\\).*/\\1/p'
    and Python's `json.dumps` default separators write `", "` and `": "`. MEASURED on run 45454429673:
    a manifest pushed with the defaults was valid OCI and unreadable to that script, which reported
    "the manifest for reactos-install has no digest or size" about a tag that was there.

usage:
    GITHUB_TOKEN=... python3 scripts/publish-disk.py DISK REPOSITORY TAG
    # e.g. disk.qcow2 easydev-org/easyvm-otheros reactos-install

The token needs `write:packages` on the repository that owns the package.
"""
import base64
import hashlib
import http.client
import json
import os
import sys

REGISTRY = "ghcr.io"
# The empty JSON document `{}`, which is what an OCI artifact uses for its config.
EMPTY_CONFIG_DIGEST = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
LAYER_MEDIA = "application/vnd.oci.image.layer.v1.tar"
CHUNK = 4 << 20


def digest_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1 << 20), b""):
            h.update(piece)
    return "sha256:" + h.hexdigest()


def bearer(repo, scope):
    credential = base64.b64encode(("x:" + os.environ["GITHUB_TOKEN"]).encode()).decode()
    conn = http.client.HTTPSConnection(REGISTRY, timeout=120)
    conn.request("GET", "/token?scope=repository:%s:%s&service=%s" % (repo, scope, REGISTRY),
                 headers={"Authorization": "Basic " + credential})
    body = json.loads(conn.getresponse().read())
    conn.close()
    return body["token"]


def upload_blob(repo, path, digest, size, token):
    """Start an upload, then PUT the whole file into the session it hands back.

    THE LOCATION HEADER IS A PATH WITH ITS OWN QUERY STRING, so the digest is appended with `&` when a
    `?` is already there - the mistake `?...&digest=` versus `?digest=` made silently on the first try.
    """
    conn = http.client.HTTPSConnection(REGISTRY, timeout=3600)
    conn.request("POST", "/v2/%s/blobs/uploads/" % repo,
                 headers={"Authorization": "Bearer " + token, "Content-Length": "0"})
    resp = conn.getresponse()
    resp.read()
    if resp.status not in (201, 202):
        sys.exit("starting the upload answered %d" % resp.status)
    location = resp.getheader("Location")
    conn.close()

    sep = "&" if "?" in location else "?"
    conn = http.client.HTTPSConnection(REGISTRY, timeout=3600)
    conn.putrequest("PUT", location + sep + "digest=" + digest)
    conn.putheader("Authorization", "Bearer " + token)
    conn.putheader("Content-Type", "application/octet-stream")
    conn.putheader("Content-Length", str(size))
    conn.endheaders()
    sent = 0
    with open(path, "rb") as f:
        while True:
            piece = f.read(CHUNK)
            if not piece:
                break
            conn.send(piece)
            sent += len(piece)
            if sent % (64 << 20) < CHUNK:
                print("  %d of %d bytes" % (sent, size), flush=True)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    if resp.status // 100 != 2:
        sys.exit("uploading the blob answered %d: %s" % (resp.status, body[:200]))


def put_manifest(repo, tag, manifest, token):
    conn = http.client.HTTPSConnection(REGISTRY, timeout=120)
    conn.request("PUT", "/v2/%s/manifests/%s" % (repo, tag), body=manifest, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/vnd.oci.image.manifest.v1+json",
        "Content-Length": str(len(manifest))})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    if resp.status // 100 != 2:
        sys.exit("putting the manifest answered %d: %s" % (resp.status, body[:400]))


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    path, repo, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    if not os.environ.get("GITHUB_TOKEN"):
        sys.exit("GITHUB_TOKEN is empty; a private package needs it")

    size = os.path.getsize(path)
    digest = digest_of(path)
    print("%s is %d bytes, %s" % (path, size, digest), flush=True)

    token = bearer(repo, "push,pull")
    upload_blob(repo, path, digest, size, token)
    # separators=(",", ":") IS NOT COSMETIC - see the module docstring.
    manifest = json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.easydev.qcow2",
        "config": {"mediaType": "application/vnd.oci.empty.v1+json",
                   "digest": EMPTY_CONFIG_DIGEST, "size": 2, "data": "e30="},
        "layers": [{"mediaType": LAYER_MEDIA, "digest": digest, "size": size,
                    "annotations": {"org.opencontainers.image.title": os.path.basename(path)}}],
    }, separators=(",", ":")).encode()
    put_manifest(repo, tag, manifest, token)
    print("pushed %s/%s:%s" % (REGISTRY, repo, tag))


if __name__ == "__main__":
    main()