#! /usr/bin/env bash
set -e

if [ -z "$(ls -A /giesela/data)" ]; then
   echo "Creating data folder"
   cp -r /giesela/_data/* /giesela/data
else
   echo "Data folder exists"
   cp -u /giesela/_data/radio_stations.yml /giesela/data
fi

exec pipenv run python run.py