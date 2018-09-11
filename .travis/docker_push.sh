#!/bin/bash

containsElement () {
  local e match="$1"
  shift
  for e; do [[ "$e" == "$match" ]] && return 0; done
  return 1
}

default_tags=("refresh" "refresh-lavalink")

if containsElement "$TRAVIS_BRANCH" "${default_tags[@]}"; then
    DOCKER_TAG="$TRAVIS_BRANCH"
fi

if [ -n "$DOCKER_TAG" ]; then
    echo "Deploying branch $TRAVIS_BRANCH with tag $DOCKER_TAG"
    echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
    docker tag "$DOCKER_REPO" "$DOCKER_REPO:$DOCKER_TAG"
    docker push "$DOCKER_REPO:$DOCKER_TAG"
fi