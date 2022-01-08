#!/bin/bash

git ls-files -- '*.md' | xargs sed -i.bak 's@\]\*\([^0-9A-Za-z[:space:][:punct:]]\)@\]* \1@g'
git ls-files -- '*.md' | xargs sed -i.bak 's@\([^0-9A-Za-z[:space:]]\)<!--@\1 <!--@g'
git ls-files -- '*.md' | xargs sed -i.bak 's@-->\([^0-9A-Za-z[:space:]]\)@--> \1@g'

find . -name '*.bak' | xargs rm

git ls-files -- '*.md' | xargs python "$(dirname ${BASH_SOURCE[0]})/learn_fix_italics.py"