#!/bin/bash

docker pull holatuwol/liferay-learn
docker run --name learn.liferay.com -p 7800:7800 -v ${PWD}:/liferay-learn holatuwol/liferay-learn