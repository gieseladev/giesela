FROM python:alpine

EXPOSE 30000

VOLUME ["/giesela/data", "/giesela/logs"]

WORKDIR /giesela

# Install Python requirements
COPY Pipfile ./
COPY Pipfile.lock ./
RUN pip install pipenv
RUN pipenv sync

COPY run.py ./
COPY giesela giesela
COPY locale locale
COPY data _data

COPY .docker/entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]