import os
import sys

def get_path(input_folder, link_file):
	if link_file[0] != '/':
		return os.path.join(input_folder, link_file)

	folder = os.getcwd()

	while not os.path.exists(os.path.join(folder, 'contents.rst')):
		folder = os.path.dirname(folder)

	return os.path.join(folder, link_file[1:])

def switch_rst_doclink(code_block_type, input_folder, line):
	x = line.find(':doc:`')

	while x != -1:
		y = line.find('`', x + 6)

		link_file = line[x+6:y] + '.md'

		link_file_path = get_path(input_folder, link_file)

		if os.path.exists(link_file_path):
			with open(link_file_path, 'r') as f:
				title = f.readlines()[0][1:].strip()
		else:
			print(link_file)
			title = link_file

		line = '%s[%s](%s)%s' % (line[:x], title, link_file, line[y+1:])

		x = line.find(':doc:`')

	return line

def switch_rst_links(code_block_type, line):
	if len(code_block_type) <= 3 or code_block_type[3] != '{':
		return line

	y = line.find('>`')

	while y != -1:
		w = line.rfind('`', 0, y)
		x = line.find('<', w)

		line = '%s[%s](%s)%s' % (line[:w], line[w+1:x].strip(), line[x+1:y].strip(), line[y+(3 if line[y+2] == '_' else 2):])

		y = line.find('>`')

	return line

def switch_rst_inline_code(code_block_type, line):
	if len(code_block_type) <= 3 or code_block_type[3] != '{':
		return line

	x = line.find('``')

	while x != -1:
		y = line.find('``', x + 2)

		if y == -1:
			return line

		line = line[:x] + line[x+1:y+1] + line[y+2:]

	return line

def fix_rst_blocks(input_file):
	with open(input_file, 'r', encoding = 'utf-8') as f:
		input_lines = f.readlines()

	fixed_lines = []
	malformed_lines = []

	in_code_block = False
	code_block_type = None
	in_directive = False

	input_folder = os.path.dirname(input_file)

	if input_folder == '':
		input_folder = '.'

	for line in input_lines:
		if line.strip().find('```') == 0:
			in_code_block = not in_code_block

			if in_code_block:
				code_block_type = line.strip()
			else:
				code_block_type = None

			fixed_lines.append(line)
			continue

		if in_code_block:
			fixed_line = line

			fixed_line = switch_rst_links(code_block_type, line)
			fixed_line = switch_rst_inline_code(code_block_type, fixed_line)

			if line != fixed_line:
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

		fixed_line = line

		fixed_line = switch_rst_doclink(code_block_type, input_folder, line)

		if line != fixed_line:
			malformed_lines.append(line)

		fixed_lines.append(fixed_line)

	if len(malformed_lines) == 0:
		return

	with open(input_file, 'w', encoding = 'utf-8') as f:
		f.write(''.join(fixed_lines))

for file in sys.argv[1:]:
	fix_rst_blocks(file)