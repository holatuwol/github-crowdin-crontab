#!/bin/bash

SCRIPT_FOLDER=$(dirname ${BASH_SOURCE[0]})

cd ${SCRIPT_FOLDER}/../liferay-learn/docs

for file in $(find . -type f -not -name '*.md' -not -name '*.rst' | grep -F '/en/'); do
	JA_FILE=$(echo "${file}" | sed 's@/en/@/ja/@g')
	mkdir -p $(dirname "${JA_FILE}")
	cp ${file} ${JA_FILE}
done

for file in $(find . -type f -name '*.md' | grep -F '/en/'); do
	JA_FILE=$(echo "${file}" | sed 's@/en/@/ja/@g')
	mkdir -p $(dirname "${JA_FILE}")

	if [ ! -f "${JA_FILE}" ]; then
		cp ${file} ${JA_FILE}
	fi
done

for file in $(find . -type f -name '*.rst' | grep -F '/en/'); do
	JA_FILE=$(echo "${file}" | sed 's@/en/@/ja/@g')
	mkdir -p $(dirname "${JA_FILE}")

	if [ ! -f "${JA_FILE}" ]; then
		cp ${file} ${JA_FILE}
	fi
done

cd -

cd ${SCRIPT_FOLDER}/../liferay-learn/site

git checkout ./build_site.sh

sed -i.bak 's/git clean/#git clean/g' build_site.sh

sed -i.bak 's@/en/@/ja/@g' build_site.sh
sed -i.bak 's/language = "en"/language = "ja"/g' docs/conf.py homepage/conf.py

if [ "${1}" == "pdf" ]; then
	if [ "" == "$(grep README ../docs/commerce/2.x/ja/contents.rst)" ]; then
		head -8 ../docs/commerce/2.x/ja/contents.rst > ../docs/commerce/2.x/ja/contents.rst.tmp
		echo '   README' >> ../docs/commerce/2.x/ja/contents.rst.tmp
		tail +9 ../docs/commerce/2.x/ja/contents.rst >> ../docs/commerce/2.x/ja/contents.rst.tmp
		rm ../docs/commerce/2.x/ja/contents.rst
		mv ../docs/commerce/2.x/ja/contents.rst.tmp ../docs/commerce/2.x/ja/contents.rst
	fi

	sed -i.bak 's/-M html/-M latexpdf/g' build_site.sh
fi

./build_site.sh

cd -

if [ "${1}" == "pdf" ]; then
	mv ../liferay-learn/site/build/output/commerce-2.x/latex/liferaylearn.pdf .
fi