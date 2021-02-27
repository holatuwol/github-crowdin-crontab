FROM jupyter/datascience-notebook

USER root

RUN apt-get update && \
	apt-get install -y openjdk-8-jdk ssh && \
	wget https://artifacts.crowdin.com/repo/deb/crowdin.deb -O crowdin.deb && \
	dpkg -i crowdin.deb

USER jovyan

RUN conda install -y bs4 requests tqdm