#!/bin/bash

if [ "$TRAVIS_BRANCH" == "refresh" ]; then
    DOCKER_TAG="refresh"
fi

if [ -n "$DOCKER_TAG" ]; then
    echo "Deploying branch $TRAVIS_BRANCH with tag $DOCKER_TAG"
    echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
    docker tag "$DOCKER_REPO" "$DOCKER_REPO:$DOCKER_TAG"
    docker push "$DOCKER_REPO:$DOCKER_TAG"
fi