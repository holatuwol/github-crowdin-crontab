from inspect import getsourcefile
from learn_util import *
import os
import re
import requests
import string
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(getsourcefile(lambda:0)))))

import git

def fix_learn_code(line):
	pos0 = line.find('https://learn.liferay.com/')

	while pos0 != -1:
		pos1 = line.find(' ', pos0)

		if pos1 == -1:
			pos1 = len(line)

		link = line[pos0:pos1]

		fixed_link = fix_learn_link(None, link)

		line = line[:pos0] + fixed_link + line[pos1:]

		pos0 = line.find('https://learn.liferay.com/', pos0 + len(fixed_link))

	return line

missing_translations = set()

def fix_learn_link(text, link):
	global missing_translations

	if link.find('https://learn.liferay.com/') != 0:
		return link

	request_url = link

	hash_index = request_url.find('#')

	if hash_index != -1:
		request_url = request_url[:hash_index]

	translated_path = '%s/docs/%s.md' % (git.rev_parse('--show-toplevel'), link[26:-5].replace('/en/', language_path))

	if os.path.isfile(translated_path):
		text_tl = extract_title_from_md(translated_path)
		link_tl = link.replace('/en/', '/%s/' % language)
		return '[%s](%s)' % (text_tl if text_tl is not None else text, link_tl) if text is not None else link

	request_url = re.sub(learn_re, '\\1/en/', request_url)

	if request_url in missing_translations:
		return '[%s](%s)' % (text, link) if text is not None else link

	r = requests.get(request_url)

	if r.status_code != 200:
		missing_translations.add(request_url)
		print('broken link:', request_url)
		return '[%s](%s)' % (text, link) if text is not None else link

	content_en = None

	if '/html' in r.headers['content-type']:
		r.encoding = r.apparent_encoding
		content_en = r.text

	r = requests.get(request_url.replace('/en/', language_path))

	if r.status_code != 200:
		missing_translations.add(request_url)
		print('missing translation to %s: %s' % (language, request_url))
		return '[%s](%s)' % (text, link) if text is not None else link

	link_tl = link.replace('/en/', '/%s/' % language)

	if content_en is None:
		return '[%s](%s)' % (text, link_tl) if text is not None else link_tl

	content_tl = None

	if '/html' in r.headers['content-type']:
		r.encoding = r.apparent_encoding
		content_tl = r.text

	pos0 = content_en.find('<h1>')

	if pos0 == -1:
		return '[%s](%s)' % (text, link_tl) if text is not None else link_tl

	pos1 = content_en.find('<', pos0 + 4)

	if text != content_en[pos0+4:pos1]:
		return '[%s](%s)' % (text, link_tl) if text is not None else link_tl

	pos0 = content_tl.find('<h1>')

	if pos0 == -1:
		return '[%s](%s)' % (text, link_tl) if text is not None else link_tl

	pos1 = content_tl.find('<', pos0 + 4)

	text_tl = content_tl[pos0+4:pos1]

	return '[%s](%s)' % (text_tl, link_tl) if text is not None else link_tl

def fix_help_center_link(text, link):
	if link.find('https://help.liferay.com/hc/') != 0:
		return link

	tl_text = get_help_center_title(link, language) if text == get_help_center_title(link, 'en-us') else text
	tl_link = link.replace('/en-us/', language_path)

	return '[%s](%s)' % (tl_text, tl_link)

def translate_line_links(input_file, base_folder, line, has_toc_tree):
	pos2 = line.find('](')

	while pos2 != -1:
		pos1 = line.rfind('[', 0, pos2)

		if pos1 == -1:
			return line

		if pos1 > 0 and line[pos1-1] == '!':
			pos2 = line.find('](', pos2 + 2)
			continue

		pos3 = line.find(')', pos2 + 2)

		if pos3 == -1:
			return line

		en_link = line[pos1:pos3+1]

		text = line[pos1+1:pos2]
		link = line[pos2+2:pos3]

		if len(link) == 0:
			pos2 = line.find('](', pos3)
			continue

		tl_link = en_link

		if link.find('https://learn.liferay.com/') == 0:
			tl_link = fix_learn_link(text, link)
		elif link.find('https://help.liferay.com/hc/') == 0:
			tl_link = fix_help_center_link(text, link)
		elif link[-3:] == '.md' and link.find('://') == -1:
			tl_file = resolve_path(base_folder, link)

			if not os.path.exists(tl_file):
				#print('[%s] broken link: %s' % (input_file, link))
				pos2 = line.find('](', pos3)
				continue

			en_file = get_en_file(tl_file)

			en_title = None

			if os.path.exists(en_file):
				en_title = extract_title_from_md(en_file)

				if text.strip().lower() != en_title.strip().lower():
					pos2 = line.find('](', pos3)
					continue
			elif not has_toc_tree:
				pos2 = line.find('](', pos3)
				continue

			tl_title = extract_title_from_md(tl_file)
			tl_link = '[%s](%s)' % (tl_title, link)

		if pos1 > 0 and not line[pos1-1].isspace():
			tl_link = ' ' + tl_link

		if pos3+1 < len(line) and not line[pos3+1].isspace():
			tl_link = tl_link + ' '

		line = line[0:pos1] + tl_link + line[pos3+1:]

		pos2 = line.find('](', pos3 - len(en_link) + len(tl_link))

	return line


def translate_links(input_file):
	with open(input_file, 'r', encoding = 'utf-8') as f:
		input_lines = f.readlines()

	has_toc_tree = ''.join(input_lines).find('```{toctree}') != -1

	fixed_lines = []
	malformed_lines = []

	in_code_block = False
	in_note_block = False
	in_directive = False
	in_comment = False

	base_folder = os.path.join(os.getcwd(), os.path.dirname(input_file))

	for line in input_lines:
		if line.find('<!--') != -1:
			in_comment = True

		if in_comment:
			if line.find('-->') != -1:
				in_comment = False

			fixed_lines.append(line)
			continue

		if line.lstrip().find('```') == 0:
			if in_note_block:
				in_note_block = False
			elif in_code_block:
				in_code_block = False
			elif line.find('{') != -1:
				in_note_block = True
			else:
				in_code_block = True

			fixed_lines.append(line)
			continue

		if in_code_block:
			fixed_line = fix_learn_code(line)

			if fixed_line != line:
				malformed_lines.append(line)

			fixed_lines.append(fixed_line)

			continue

		if line.find('..') == 0:
			in_directive = True
			fixed_lines.append(line)
			continue

		if in_directive:
			if len(line.strip()) == 0:
				fixed_lines.append(line)
				continue

			if line[0].isspace():
				fixed_lines.append(line)
				continue

			in_directive = False

		fixed_line = translate_line_links(input_file, base_folder, line, has_toc_tree)

		if fixed_line != line:
			malformed_lines.append(line)

		fixed_lines.append(fixed_line)

	if len(malformed_lines) == 0:
		return

#	print(input_file)
#	print(''.join(malformed_lines))

	with open(input_file, 'w', encoding = 'utf-8') as f:
		f.write(''.join(fixed_lines))

files = []

if len(sys.argv) == 1:
	files = [
		os.path.join(basedir, file_name)
			for basedir, _, file_name_list in os.walk(os.getcwd())
				for file_name in file_name_list
	]
else:
	files = sys.argv[1:]

print('Checking %d files' % len(files))

for file in files:
	translate_links(file)