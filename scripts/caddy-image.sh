#!/usr/bin/env bash
#
# Put the Caddy image for this commit under the name CI checks and pushes.
#
#     scripts/caddy-image.sh <ghcr.io/owner/repo/caddy> <name to give it>
#
# **Caddy is rebuilt from source only when its source changed.** `deploy/caddy`
# changes a few times a year, and the build downloads about two hundred Go
# modules and checks each against sum.golang.org. Run on every pull request and
# every push to main, that is a network dependency in a job that has no other
# reason to fail on one: run 525 on main (afbca90) died with
# `reading https://sum.golang.org/tile/...: stream error ... INTERNAL_ERROR;
# received from peer`, in a commit that touched nothing under deploy/, and the
# same Dockerfile had built on the pull request.
#
# The image published for the last commit that changed `deploy/caddy` was built
# from exactly the files in the directory now, so it is the image this commit
# would build. If it is there it is pulled and renamed; nothing is built and
# nothing is downloaded from the Go proxy. If it is not (this commit changes
# `deploy/caddy`, or the tag was never published, or the registry will not answer)
# it is built, which is also what makes a Dockerfile change get built on its pull
# request.
#
# One pull, and one build when there is nothing to pull. There is no loop: a
# build that fails fails the job, which says what failed.
#
# Needs the whole history (`fetch-depth: 0`): "the last commit that changed a
# directory" is a question about history, and a shallow checkout answers it with
# the only commit it has.

set -euo pipefail

repository=${1:?the caddy image repository, e.g. ghcr.io/owner/repo/caddy}
name=${2:?the name to give the image}

last=$(git log -1 --format=%H -- deploy/caddy)

if [ -n "$last" ] && docker pull "$repository:$last" > /dev/null 2>&1; then
  echo "deploy/caddy last changed in $last; reusing $repository:$last"
  docker tag "$repository:$last" "$name"
  exit 0
fi

echo "no published image for deploy/caddy at ${last:-no commit}; building it"
docker build -t "$name" deploy/caddy
