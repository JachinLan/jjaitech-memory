#!/bin/bash
set -eu
if [ "$(uname -s)" != Darwin ]; then echo 'This command requires macOS.' >&2; exit 1; fi
jj_dir=$(mktemp -d "${TMPDIR:-/tmp}/jjaitech-install.XXXXXX")
trap 'rm -rf -- "$jj_dir"' EXIT
curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 --output "$jj_dir/release.zip" https://github.com/JachinLan/jjaitech-memory/releases/download/v1.4.1-rc.1-online.1/jjaitech-memory-1.4.1-rc.1-online.1.zip
jj_hash=$(shasum -a 256 "$jj_dir/release.zip" | awk '{print $1}')
if [ "$jj_hash" != d5339dc66312925444becaa9dadab7a03083fc5286ad9a2820b1d8fad10a3edb ]; then echo 'Download checksum mismatch; stopped.' >&2; exit 1; fi
unzip -q "$jj_dir/release.zip" -d "$jj_dir/package"
bash "$jj_dir/package/jjaitech-memory/distribution/bootstrap-macos.sh" "$jj_dir/package" "$@"
