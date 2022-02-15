from learn_util import *
import os
import requests
import string
import subprocess
import sys

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

def fix_learn_link(text, link):
	if link.find('https://learn.liferay.com/') != 0:
		return link

	request_url = link

	hash_index = request_url.find('#')

	if hash_index != -1:
		request_url = request_url[:hash_index]

	if request_url.find('/ja/') != -1:
		request_url = request_url.replace('/ja/', '/en/')

	r = requests.get(request_url)

	if r.status_code == 200:
		content_en = None

		if '/html' in r.headers['content-type']:
			r.encoding = r.apparent_encoding
			content_en = r.text

		request_url = request_url.replace('/en/', '/ja/')

		r = requests.get(request_url)

		if r.status_code != 200:
			print('missing translation:', request_url)
			return '[%s](%s)' % (text, link) if text is not None else link

		content_ja = None

		if '/html' in r.headers['content-type']:
			r.encoding = r.apparent_encoding
			content_ja = r.text

		pos0 = content_en.find('<h1>')
		link_ja = link.replace('/en/', '/ja/')

		if pos0 == -1:
			return '[%s](%s)' % (text, link_ja) if text is not None else link_ja

		pos1 = content_en.find('<', pos0 + 4)

		if text != content_en[pos0+4:pos1]:
			return '[%s](%s)' % (text, link_ja) if text is not None else link_ja

		pos0 = content_ja.find('<h1>')

		if pos0 == -1:
			return '[%s](%s)' % (text, link_ja) if text is not None else link_ja

		pos1 = content_ja.find('<', pos0 + 4)

		text_ja = content_ja[pos0+4:pos1]

		return '[%s](%s)' % (text_ja, link_ja) if text is not None else link_ja

	print('broken link:', request_url)
	return '[%s](%s)' % (text, link) if text is not None else link

def translate_line_links(base_folder, line):
	pos2 = line.find('](')

	while pos2 != -1:
		pos1 = line.rfind('[', 0, pos2)

		if pos2 == -1:
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

		ja_link = en_link

		if link.find('https://learn.liferay.com/') == 0:
			if link.find('/en/') != -1 or link.find('/ja/') != -1:
				ja_link = fix_learn_link(text, link)
		elif link[0] == '.' and link[-3:] == '.md':
			ja_file = resolve_path(base_folder, link)
			en_file = get_en_file(ja_file)

			if not os.path.exists(en_file) or not os.path.exists(ja_file):
				pos2 = line.find('](', pos3)
				continue

			en_title = extract_title_from_md(en_file)

			if text != en_title:
				pos2 = line.find('](', pos3)
				continue

			ja_title = extract_title_from_md(ja_file)
			ja_link = '[%s](%s)' % (ja_title, link)

		if pos1 > 0 and not line[pos1-1].isspace():
			ja_link = ' ' + ja_link

		if pos3+1 < len(line) and not line[pos3+1].isspace():
			ja_link = ja_link + ' '

		line = line[0:pos1] + ja_link + line[pos3+1:]

		pos2 = line.find('](', pos3 - len(en_link) + len(ja_link))

	return line


def translate_links(input_file):
	with open(input_file, 'r', encoding = 'utf-8') as f:
		input_lines = f.readlines()

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

		if line.find('```') == 0:
			if in_note_block:
				in_note_block = False
			elif in_code_block:
				in_code_block = False
			elif line[3] == '{':
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

		fixed_line = translate_line_links(base_folder, line)

		if fixed_line != line:
			malformed_lines.append(line)

		fixed_lines.append(fixed_line)

	if len(malformed_lines) == 0:
		return

#	print(input_file)
#	print(''.join(malformed_lines))

	with open(input_file, 'w', encoding = 'utf-8') as f:
		f.write(''.join(fixed_lines))

for file in sys.argv[1:]:
	translate_links(file)