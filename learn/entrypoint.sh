#!/bin/bash

rm -rf /liferay-learn/site/venv
rm -rf /liferay-learn/site/build

build_learn() {
	local CLEAN_BUILD='y'

	if [ -d liferay-learn-build ]; then
		CLEAN_BUILD='n'
	fi

	mkdir liferay-learn-build

	find liferay-learn/ -name '*.rst' | xargs dos2unix

	rsync -rvci liferay-learn/ liferay-learn-build/ | tee changed_files.txt

	cd /liferay-learn-build/site

	sed -i 's@python3 -m venv venv@python3 -m venv /opt/venv@g' build_site.sh
	sed -i 's@source venv/bin/activate@source /opt/venv/bin/activate@g' build_site.sh
	sed -i 's@mv build/output/@cp -R build/output/@g' build_site.sh

	if [ "n" == "${CLEAN_BUILD}" ]; then
		sed -i 's#rm -fr build#cat /changed_folders.txt | sed "s@../docs/@build/output/@g" | xargs -r rm -rf#g' build_site.sh
		sed -i 's@for docs_dir_name in.*$@for docs_dir_name in $(cat /changed_folders.txt)@g' build_site.sh
		grep -o 'docs/[^/]*/[^/]*/[^/]*/' /changed_files.txt | sort -u | grep -vF '_template' | awk '{ print "../" $1 }' > /changed_folders.txt
	fi

	./build_site.sh
}

start_learn() {
	echo 'Starting server on port 7800...'
	cd /liferay-learn-build/site/build/output
	python -m http.server 7800
}

build_learn
start_learn
