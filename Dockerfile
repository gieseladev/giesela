FROM python:stretch

LABEL maintainer=Simon

EXPOSE 30000

# Install required packages
RUN apt-get -yqq update
RUN apt-get -yqq --no-install-recommends install ffmpeg

VOLUME ["/giesela/data", "/giesela/logs"]

WORKDIR /giesela

# Install Python requirements
COPY Pipfile ./
COPY Pipfile.lock ./
RUN pip install pipenv
RUN pipenv sync

# Cleanup
RUN apt-get clean
RUN rm -rf /var/lib/apt/lists/*

COPY run.py ./
COPY giesela giesela
COPY locale locale
COPY data _data

COPY .docker/entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]