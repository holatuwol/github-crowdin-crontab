from inspect import getsourcefile
from myst_parser.main import MdParserConfig, default_parser
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(getsourcefile(lambda:0)))))

import git

def get_markdown_parser(max_heading_level):
	# Copied from https://github.com/executablebooks/MyST-Parser/blob/v0.16.1/myst_parser/cli.py

	config = MdParserConfig(renderer="html", heading_anchors=max_heading_level)
	parser = default_parser(config)

	def _filter_tokens(state):
		state.tokens = [
			t for t in state.tokens
				if t.type.startswith("heading_") and int(t.tag[1]) <= max_heading_level
		]

	parser.use(lambda p: p.core.ruler.push("filter", _filter_tokens))

	return parser

def is_matching_heading(line):
	if line[0] != '#':
		return False

	for i in range(1, max_heading_level):
		if line[i] != '#':
			return True

	return line[max_heading_level] != '#'

def get_header_anchor(line):
	return '<a name="%s" />\n' % line.split('"')[1]

def update_header_ids(ja_file, max_heading_level):
	parser = get_markdown_parser(max_heading_level)

	en_file = os.path.join(os.getcwd(), ja_file).replace('/ja/', '/en/')

	if not os.path.exists(en_file):
		return

	with open(en_file, 'r', encoding = 'utf-8') as f:
		header_anchors = [
			get_header_anchor(line)
				for line in parser.render(f.read()).split('\n')
					if len(line.strip()) > 0
		]

	header_index = 0

	with open(ja_file, 'r', encoding = 'utf-8') as f:
		input_lines = f.readlines()

	in_code_block = False
	in_note_block = False
	in_directive = False
	in_comment = False

	fixed_lines = []
	translated_header_anchors = []
	updated_file = False

	for i, line in enumerate(input_lines):
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
			fixed_lines.append(line)
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

		if is_matching_heading(line) and header_index < len(header_anchors):
			translated_header_anchors.append(line)

			if len(fixed_lines) < 2:
				updated_file = False
			elif fixed_lines[-1] == '\n' and fixed_lines[-2].find('<a name="') == -1:
				updated_file = True
				fixed_lines.append(header_anchors[header_index])
				fixed_lines.append('\n')
			elif fixed_lines[-1] == '\n' and fixed_lines[-2].find('<a name="') == 0:
				updated_file = True
				fixed_lines[-2] = header_anchors[header_index]
			else:
				if fixed_lines[-1] != '\n':
					fixed_lines.append('\n')

				fixed_lines.append(header_anchors[header_index])
				fixed_lines.append('\n')

			header_index = header_index + 1

		fixed_lines.append(line)
		previous_line = line

	if not updated_file:
		return True

	if header_index != len(header_anchors):
		print('mismatched header count:', header_index, len(header_anchors), ja_file)
		return False

	with open(ja_file, 'w', encoding = 'utf-8') as f:
		f.write(''.join(fixed_lines))

	return True

files = []

if len(sys.argv) == 1:
	files = git.ls_files('*.md').split('\n')
else:
	files = sys.argv[1:]

for file in files:
	if not update_header_ids(file, 3):
		update_header_ids(file, 2)