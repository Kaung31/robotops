#!/usr/bin/env bash
# Pinned upstream actionlint release, verified before executing the downloaded tool.
set -euo pipefail
version=1.7.7
archive=.ci-results/tools/actionlint.tar.gz
mkdir -p .ci-results/tools
curl --fail --silent --show-error --location \
  "https://github.com/rhysd/actionlint/releases/download/v${version}/actionlint_${version}_linux_amd64.tar.gz" \
  --output "$archive"
printf '%s  %s\n' \
  023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757 "$archive" \
  | sha256sum --check -
tar -xzf "$archive" -C .ci-results/tools actionlint
.ci-results/tools/actionlint -color
shellcheck scripts/ci/*.sh
