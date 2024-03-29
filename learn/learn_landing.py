#!/usr/bin/env python

from inspect import getsourcefile
from learn_util import *
import json
import os
import requests
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(getsourcefile(lambda:0)))))

import git

def extract_string_value(line):
	if line.find('`') != -1:
		sep = '`'
	elif line.find('"') != -1:
		sep = '"'
	else:
		sep = '\''

	return line[line.find(sep)+1:line.rfind(sep)]

def set_string_value(line, value):
	if line.find('`') != -1:
		sep = '`'
		escaped_value = value
	elif line.find('"') != -1:
		sep = '"'
		escaped_value = value.replace('"', '\\\"')
	else:
		sep = '\''
		escaped_value = value.replace('\'', '\\\'')

	prefix = line[:line.find(sep)+1]
	suffix = line[line.rfind(sep):]

	return '%s%s%s' % (prefix, escaped_value, suffix)

def extract_title(landing_file_name, html_file_name):
	base_name = os.path.dirname(os.path.abspath(landing_file_name))

	if len(os.path.basename(base_name)) > 2:
		base_name = os.path.dirname(base_name)

	file_name = '%s.md' % html_file_name[:html_file_name.rfind('.')]
	file_path = os.path.join(base_name, file_name)

	if os.path.exists(file_path):
		return file_path, extract_title_from_md(file_path)

	file_name = '%s.rst' % html_file_name[:html_file_name.rfind('.')]
	file_path = os.path.join(base_name, file_name)

	if os.path.exists(file_path):
		return file_path, extract_title_from_rst(file_path)

	return file_path, None

def update_landing(file_name):
	new_content = []

	with open(file_name, encoding='utf-8', mode = 'r') as f:
		old_content = f.readlines()

	name_line = None
	has_error = False

	for i, line in enumerate(old_content):
		if line.find('sectionName:') != -1 or line.find('name:') != -1:
			name_line = line
			continue

		if name_line is None:
			new_content.append(line)
			continue

		path_line = line

		if path_line.find('url') == -1 and path_line.find('URL') == -1:
			new_content.append(name_line)
		else:
			relative_path = extract_string_value(path_line)

			if relative_path.find('https://') == 0:
				absolute_path, new_title = get_help_center_title(relative_path, 'ja')
				new_content.append(name_line if new_title is None else set_string_value(name_line, new_title))
				new_content.append(path_line if absolute_path is None else set_string_value(path_line, absolute_path))
				name_line = None
				continue

			if len(relative_path) == 0:
				new_content.append(name_line)
				continue

			absolute_path, new_title = extract_title(file_name, relative_path.strip())

			if new_title is None:
				if os.path.exists(absolute_path):
					print('[%s:%d] Unable to extract title from path: %s' % (file_name, i, relative_path))
				else:
					print('[%s:%d] Unable to find file: %s' % (file_name, i, relative_path))

				new_content.append(name_line)
				has_error = True
			else:
				new_content.append(set_string_value(name_line, new_title))

		new_content.append(path_line)

		name_line = None

	with open(file_name, 'w', encoding = 'utf-8') as f:
		f.write(''.join(new_content))

files = []

if len(sys.argv) == 1:
	files = git.ls_files('landing.html', '**/landing.html').split('\n')
else:
	files = sys.argv[1:]

for file in files:
	update_landing(file)