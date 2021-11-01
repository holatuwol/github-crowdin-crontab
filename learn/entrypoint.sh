#!/bin/bash

rm -rf /liferay-learn/site/venv
rm -rf /liferay-learn/site/build

mkdir -p liferay-learn-build

rsync -rvci liferay-learn/ liferay-learn-build/ | tee changed_files.txt
grep -vF contents.rst changed_files.txt | grep -o 'docs/[^/]*/[^/]*/[^/]*/' > changed_folders.txt

if [[ 0 -ne $(cat changed_folders.txt | wc -c) ]]; then
	cd /liferay-learn-build

	for file in $(find docs -name 'contents.rst'); do
		if [ "" == "$(grep "$(dirname ${file})" ../changed_folders.txt)" ]; then
			rm ${file}
		fi
	done

	cd site

	sed -i 's@python3 -m venv venv@python3 -m venv /opt/venv@g' build_site.sh
	sed -i 's@source venv/bin/activate@source /opt/venv/bin/activate@g' build_site.sh

	./build_site.sh
fi

echo 'Starting server on port 7800...'

cd /liferay-learn-build/site/build/output
python -m http.server 7800