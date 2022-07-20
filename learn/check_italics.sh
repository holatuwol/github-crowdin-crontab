#!/bin/bash

if [ -z "$@" ]; then
	git ls-files -- '*.md' | xargs sed -i.bak 's@\]\*\([^0-9A-Za-z[:space:][:punct:]]\)@\]* \1@g'
	git ls-files -- '*.md' | xargs sed -i.bak 's@\([^0-9A-Za-z[:space:]]\)<!--@\1 <!--@g'
	git ls-files -- '*.md' | xargs sed -i.bak 's@-->\([^0-9A-Za-z[:space:]]\)@--> \1@g'

	while [ "" != "$(git ls-files -- '*.md' | xargs grep -F '***')" ]; do
		git ls-files -- '*.md' | xargs sed -i.bak 's@\*\*\*@**@g'
	done
else
	sed -i.bak 's@\]\*\([^0-9A-Za-z[:space:][:punct:]]\)@\]* \1@g' $@
	sed -i.bak 's@\([^0-9A-Za-z[:space:]]\)<!--@\1 <!--@g' $@
	sed -i.bak 's@-->\([^0-9A-Za-z[:space:]]\)@--> \1@g' $@
fi

find . -name '*.bak' | xargs rm

if [ -z "$@" ]; then
	git ls-files -- '*.md' | xargs python "$(dirname ${BASH_SOURCE[0]})/learn_fix_italics.py"
else
	python "$(dirname ${BASH_SOURCE[0]})/learn_fix_italics.py" $@
fi