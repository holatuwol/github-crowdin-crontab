FROM python:3.8

RUN apt-get update
RUN apt install -y pipenv rsync

COPY Pipfile /
Copy Pipfile.lock /

ENV VIRTUAL_ENV=/opt/venv

RUN mkdir -p /opt/venv && \
    python3 -m venv ${VIRTUAL_ENV}

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install pipenv && \
    pipenv install

EXPOSE 7800

RUN apt install -y dos2unix jq p7zip p7zip-full

COPY entrypoint.sh /

RUN chmod a+x entrypoint.sh

ENTRYPOINT ./entrypoint.sh