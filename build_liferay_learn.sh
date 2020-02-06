#!/bin/bash

cd $(dirname ${BASH_SOURCE[0]})/../liferay-learn/docs
for file in $(find . -type f -not -name '*.md' | grep -F '/en/'); do mkdir -p $(echo "${file}" | sed 's@/en/@/ja/@g' | xargs dirname); cp ${file} $(echo "${file}" | sed 's@/en/@/ja/@g'); done
cd ../site
sed -i.bak 's/git clean/#git clean/g' build_site.sh
./build_site.sh